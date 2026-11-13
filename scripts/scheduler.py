"""
每日自动化调度（APScheduler）

功能：每个交易日收盘后自动执行全流程：
  增量采集行情 → 增量采集财报 → 因子计算 → 生成信号 → PaperBroker 模拟盘

用法：
  python scripts/scheduler.py                # 前台运行（Ctrl-C 停止）
  python scripts/scheduler.py --run-now      # 立即执行一次（不等定时）
  python scripts/scheduler.py --time 15:30   # 每交易日 15:30 执行（默认）

红线：
- 幂等：同一天重复执行不重复入账（采集按日期增量、订单按 order_id 去重）
- 可单独重跑：每个环节独立函数，任何一步失败不影响其他环节留痕
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.logger import get_logger  # noqa: E402

log = get_logger("scheduler", log_dir=str(ROOT / "logs"))

DB = ROOT / "data" / "quant.db"


# ----------------------------------------------------------------------
# 环节 1：增量采集行情（仅补最近 N 日缺失）
# ----------------------------------------------------------------------
def step_fetch_recent(days: int = 10) -> bool:
    """增量采集所有已入库标的的最近 N 日行情（幂等：日期去重）。"""
    from data.cleaner import clean_daily_bars
    from data.fetcher.akshare_fetcher import AkshareFetcher
    from data.storage import Storage

    bars_dir = ROOT / "data" / "bars"
    codes = sorted(p.stem for p in bars_dir.glob("*.parquet"))
    if not codes:
        log.warning("[step1] 本地无行情，跳过增量采集（先跑 fetch_universe）")
        return True

    storage = Storage(str(DB), str(bars_dir))
    fetcher = AkshareFetcher()
    import pandas as pd

    start = (pd.Timestamp.now() - pd.Timedelta(days=days * 2)).strftime("%Y%m%d")
    end = pd.Timestamp.now().strftime("%Y%m%d")

    ok, fail = 0, 0
    t0 = time.time()
    for i, code in enumerate(codes):
        try:
            old = storage.load_bars(code)
            if old is not None and len(old):
                last_date = pd.to_datetime(old["date"]).max()
                new_start = (last_date + pd.Timedelta(days=1)).strftime("%Y%m%d")
                if new_start > end:
                    ok += 1
                    continue  # 已是最新
                start_use = new_start
            else:
                start_use = start
            raw = fetcher.fetch_daily_bars(code, start_use, end, with_adj_factor=False)
            if raw is not None and not raw.empty:
                # 合并去重入库
                merged = pd.concat([old, raw], ignore_index=True) if old is not None and len(old) else raw
                merged["date"] = pd.to_datetime(merged["date"])
                merged = merged.drop_duplicates(subset="date", keep="last").sort_values("date")
                # 红线防御：with_adj_factor=False 的新行因子=1.0，直接合并会把
                # 复权因子塌成 1（真实踩坑：000534 因子 4.29→1.0，放大/缩小百倍）。
                # 修法：新行因子视为缺失，合并后按时间 ffill 继承旧因子。
                if old is not None and len(old):
                    old_dates = set(pd.to_datetime(old["date"]))
                    new_mask = merged["date"].isin(old_dates) == False  # noqa: E712
                    merged.loc[new_mask, "adj_factor"] = float("nan")
                    merged["adj_factor"] = pd.to_numeric(merged["adj_factor"], errors="coerce")
                    merged["adj_factor"] = merged["adj_factor"].ffill().fillna(1.0)
                else:
                    merged["adj_factor"] = merged.get("adj_factor", 1.0)
                storage.save_bars(code, merged)
            ok += 1
        except Exception as e:  # noqa: BLE001
            fail += 1
            log.warning(f"[step1] {code} 增量失败: {type(e).__name__}")
        if (i + 1) % 200 == 0:
            log.info(f"[step1] {i + 1}/{len(codes)}（ok={ok} fail={fail}）")
        time.sleep(0.3)
    log.info(f"[step1] 行情增量完成：ok={ok} fail={fail}（{time.time() - t0:.0f}s）")
    return True


# ----------------------------------------------------------------------
# 环节 2：增量采集最新财报
# ----------------------------------------------------------------------
def step_fetch_fundamentals() -> bool:
    """采集最新报告期财报（幂等：UPSERT by code+period）。"""
    import pandas as pd
    sys.path.insert(0, str(ROOT / "scripts"))
    from fetch_fundamentals import all_quarters, fetch_quarter, init_table, upsert

    conn = sqlite3.connect(str(DB))
    init_table(conn)
    # 只采最近 2 个报告期（增量）
    for q in all_quarters()[-2:]:
        try:
            df = fetch_quarter(q)
            if df is not None and not df.empty:
                n = upsert(conn, df)
                log.info(f"[step2] 财报 {q}: {n} 条")
        except Exception as e:  # noqa: BLE001
            log.warning(f"[step2] 财报 {q} 失败: {type(e).__name__}")
        time.sleep(3)
    conn.close()
    return True


# ----------------------------------------------------------------------
# 环节 3：真实下单（run-paper --qmt 子进程，与手工链路完全一致）
# ----------------------------------------------------------------------
def step_run_signals(top_n: int = 50, lam: float = 0.5,
                     capital: float = 1_000_000.0) -> bool:
    """跑真实 QMT 下单链路（重放→目标持仓→差额→风控→限价委托）。

    与手工 `python main.py run-paper --qmt --lam L --top-n N --capital C` 完全一致：
    内部自带前置撤旧单（cancel_stale）+ 结算同步（sync_settle）+ 净值留痕。
    """
    import subprocess
    import sys as _sys

    cmd = [_sys.executable, "main.py", "run-paper", "--qmt",
           "--lam", str(lam), "--top-n", str(top_n), "--capital", str(int(capital))]
    log.info(f"[step3] run-paper 启动：{' '.join(cmd[1:])}")
    t0 = time.time()
    r = subprocess.run(cmd, cwd=str(ROOT),
                       capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=3600)
    out = (r.stdout or "") + (r.stderr or "")
    # 日志留档（每次运行独立文件，供运行中心查看）
    log_dir = ROOT / "logs"
    log_dir.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_log = log_dir / f"run_paper_{stamp}.log"
    run_log.write_text(out, encoding="utf-8")
    ok = r.returncode == 0
    tail = [ln for ln in out.splitlines() if ln.strip()][-8:]
    for ln in tail:
        log.info(f"[step3] {ln}")
    log.info(f"[step3] run-paper {'完成' if ok else '失败'}（exit={r.returncode}，"
             f"{time.time() - t0:.0f}s，日志 {run_log.name}）")
    return ok


# ----------------------------------------------------------------------
# 主流程
# ----------------------------------------------------------------------
def run_daily_job(top_n: int = 50, lam: float = 0.5, capital: float = 1_000_000.0):
    """每日全流程（各环节独立 try，失败不阻断后续环节留痕）。整体登记 runs registry。"""
    from scripts.runs_registry import finish_run, start_run

    log_file = log.handlers[0].baseFilename if log.handlers else ""
    rid = start_run("daily_job", f"每日全流程 λ={lam} TopN={top_n}",
                    "scheduler daily job", log_file, os.getpid())
    log.info("========== 每日任务开始 ==========")
    t0 = time.time()
    failed = False

    # 防重护栏：当日已成功下过单（run_paper_qmt/daily_job）则跳过下单环节
    # （幂等保护——同日重复触发不重复委托；撤旧单是最后防线，此处先省事）
    from scripts.runs_registry import load_runs
    today = datetime.now().strftime("%Y-%m-%d")
    already = any(
        r.get("status") == "done" and (r.get("ts_start") or "").startswith(today)
        and r.get("key") in ("daily_job", "run_paper_qmt")
        for r in load_runs(limit=50)
    )
    if already:
        log.info("[daily] 当日已有成功下单记录，跳过下单环节（防重复委托）")
    else:
        steps = (
            ("行情增量", lambda: step_fetch_recent()),
            ("财报增量", step_fetch_fundamentals),
            ("信号+模拟盘", lambda: step_run_signals(top_n=top_n, lam=lam,
                                                     capital=capital)),
        )
        for name, fn in steps:
            try:
                fn()
            except Exception as e:  # noqa: BLE001
                failed = True
                log.error(f"[daily] 环节「{name}」异常: {type(e).__name__} {str(e)[:120]}")

    # 收尾环节始终执行（幂等）
    for name, fn in (
        ("实盘净值留痕", lambda: _step_paper_equity()),
        ("交易日报", lambda: _step_daily_report()),
    ):
        try:
            fn()
        except Exception as e:  # noqa: BLE001
            failed = True
            log.error(f"[daily] 环节「{name}」异常: {type(e).__name__} {str(e)[:120]}")
    log.info(f"========== 每日任务完成（{time.time() - t0:.0f}s）==========")
    finish_run(rid, "failed" if failed else "done", None)


def run_data_job():
    """盘后数据任务（15:05）：只做行情+财报增量，不下单。

    与盘前任务（run_premarket_job）拆分：收盘后尽快把当日数据补齐，
    盘前重放才有最新因子/行情可算。
    """
    from scripts.runs_registry import finish_run, start_run

    log_file = log.handlers[0].baseFilename if log.handlers else ""
    rid = start_run("data_job", "盘后数据增量（行情+财报）",
                    "scheduler data job", log_file, os.getpid())
    log.info("========== 盘后数据任务开始 ==========")
    t0 = time.time()
    failed = False
    for name, fn in (
        ("行情增量", lambda: step_fetch_recent()),
        ("财报增量", step_fetch_fundamentals),
    ):
        try:
            fn()
        except Exception as e:  # noqa: BLE001
            failed = True
            log.error(f"[data] 环节「{name}」异常: {type(e).__name__} {str(e)[:120]}")
    log.info(f"========== 盘后数据任务完成（{time.time() - t0:.0f}s）==========")
    finish_run(rid, "failed" if failed else "done", None)


def run_premarket_job(top_n: int = 50, lam: float = 0.5,
                       capital: float = 1_000_000.0):
    """盘前任务（08:30）：策略生成当日买卖计划 + QMT 委托。

    前置依赖：昨日盘后 data_job 已把行情补齐（昨日收盘数据可算因子）。
    用户可在开盘前（如 09:00）打开 web「今日交易计划」查看当日买卖单。
    """
    from scripts.runs_registry import finish_run, start_run

    log_file = log.handlers[0].baseFilename if log.handlers else ""
    rid = start_run("premarket_job", f"盘前策略生成 λ={lam} TopN={top_n}",
                    "scheduler premarket job", log_file, os.getpid())
    log.info("========== 盘前任务开始 ==========")
    t0 = time.time()
    failed = False

    # 防重护栏：当日已成功下过单则跳过（同 daily_job 语义）
    from scripts.runs_registry import load_runs
    today = datetime.now().strftime("%Y-%m-%d")
    already = any(
        r.get("status") == "done" and (r.get("ts_start") or "").startswith(today)
        and r.get("key") in ("daily_job", "run_paper_qmt", "premarket_job")
        for r in load_runs(limit=50)
    )
    if already:
        log.info("[premarket] 当日已有成功下单记录，跳过（防重复委托）")
    else:
        try:
            step_run_signals(top_n=top_n, lam=lam, capital=capital)
        except Exception as e:  # noqa: BLE001
            failed = True
            log.error(f"[premarket] 下单环节异常: {type(e).__name__} {str(e)[:120]}")

    # 净值留痕（幂等）：盘前跑一次，把昨日收盘后的柜台状态留痕
    try:
        _step_paper_equity()
    except Exception as e:  # noqa: BLE001
        log.error(f"[premarket] 净值留痕异常: {type(e).__name__}")
    log.info(f"========== 盘前任务完成（{time.time() - t0:.0f}s）==========")
    finish_run(rid, "failed" if failed else "done", None)


def _step_paper_equity() -> bool:
    """实盘净值留痕（QMT 柜台总资产 → data/paper_equity.csv，幂等）。"""
    from scripts.paper_equity import record
    msg = record()
    log.info(f"[step5] {msg}")
    return True


def _step_sync_settle() -> bool:
    """结算同步：柜台终态对齐台账 + 订单状态回写（批次撮合延迟后必跑）。

    东莞柜台批次撮合延迟 30-50 分钟：run-paper 委托时的「执行后对齐」拿到
    的是旧快照，成交陆陆续续到账后无人再同步 → 台账停旧、持仓页看不到
    当日买入。本环节在每日收尾任务跑一次，当日成交自动落台账。
    """
    try:
        from scripts.sync_settle import sync
        sync(verbose=False)
        log.info("[sync] 结算同步完成（柜台终态已对齐台账）")
        return True
    except Exception as e:  # noqa: BLE001
        log.error(f"[sync] 结算同步异常: {type(e).__name__} {str(e)[:120]}")
        return False


def _step_daily_report() -> bool:
    """交易日报（report/daily/YYYY-MM-DD.md）。"""
    from scripts.daily_report import generate
    out = generate()
    log.info(f"[step6] 日报已生成 {out.name}")
    return True


def main():
    parser = argparse.ArgumentParser(description="每日自动化调度")
    parser.add_argument("--time", default="08:30",
                        help="盘前策略生成时刻（默认 08:30；生成当日买卖计划并 QMT 委托）")
    parser.add_argument("--data-time", default="15:05",
                        help="盘后数据增量时刻（默认 15:05；行情+财报补齐，不下单）")
    parser.add_argument("--run-now", action="store_true", help="立即执行一次盘前全流程")
    parser.add_argument("--run-data", action="store_true",
                        help="立即执行一次盘后数据任务（行情+财报增量）")
    parser.add_argument("--top-n", type=int, default=100)
    parser.add_argument("--lam", type=float, default=0.5)
    parser.add_argument("--capital", type=float, default=1_000_000.0,
                        help="目标仓位资金（100 万口径，默认 1000000）")
    parser.add_argument("--run-fetch-recent", type=int, default=0, metavar="DAYS",
                        help="只跑环节1：增量采集最近 N 日行情后退出（看板控制台用）")
    args = parser.parse_args()

    if args.run_fetch_recent:
        ok = step_fetch_recent(args.run_fetch_recent)
        sys.exit(0 if ok else 1)

    if args.run_data:
        run_data_job()
        return

    if args.run_now:
        run_daily_job(top_n=args.top_n, lam=args.lam, capital=args.capital)
        return

    # APScheduler 定时：交易日（周一~五）
    try:
        from apscheduler.schedulers.blocking import BlockingScheduler
    except ImportError:
        log.error("APScheduler 未安装：pip install apscheduler")
        sys.exit(1)

    def _mk(hhmm: str) -> tuple[int, int]:
        hh, mm = hhmm.split(":")
        return int(hh), int(mm)

    pm_h, pm_m = _mk(args.time)
    dm_h, dm_m = _mk(args.data_time)
    sched = BlockingScheduler()

    # 盘前任务：策略生成当日买卖计划 + QMT 委托（默认 08:30）
    sched.add_job(
        lambda: run_premarket_job(top_n=args.top_n, lam=args.lam,
                                  capital=args.capital),
        trigger="cron",
        day_of_week="mon-fri",
        hour=pm_h, minute=pm_m,
        id="premarket_quant_job",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=3600,
    )
    # 盘后数据任务：行情+财报增量（默认 15:05，收盘后尽快补齐当日数据）
    sched.add_job(
        lambda: run_data_job(),
        trigger="cron",
        day_of_week="mon-fri",
        hour=dm_h, minute=dm_m,
        id="data_quant_job",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=7200,
    )
    # 盘中对齐任务：11:35 / 14:35 两次结算同步（盘前委托的成交陆续回来，
    # 台账及时对齐柜台——批次撮合延迟 30-50 分钟，2 个时点足够收敛）
    sched.add_job(
        lambda: _step_sync_settle(),
        trigger="cron",
        day_of_week="mon-fri",
        hour="11,14", minute=35,
        id="midday_sync_job",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=3600,
    )
    # 交易日报：盘后数据补齐后生成（默认 15:40，避开数据任务运行窗口）
    # 结算同步前置：当日批次撮合成交落台账（持仓页当天可见当日买入）
    sched.add_job(
        lambda: (_step_sync_settle(), _step_daily_report(), _step_paper_equity()),
        trigger="cron",
        day_of_week="mon-fri",
        hour=dm_h, minute=min(dm_m + 35, 59),
        id="daily_report_job",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=7200,
    )

    log.info(f"[scheduler] 已启动：盘前策略 {args.time} · 盘后数据 {args.data_time} ·"
             f" 日报 {args.data_time}+35min（Ctrl-C 停止）")
    try:
        sched.start()
    except (KeyboardInterrupt, SystemExit):
        log.info("[scheduler] 已停止")


if __name__ == "__main__":
    main()
