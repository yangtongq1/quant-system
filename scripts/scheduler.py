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
# 环节 3：生成信号 + PaperBroker 模拟盘
# ----------------------------------------------------------------------
def step_run_signals(top_n: int = 50, lam: float = 0.5) -> bool:
    """用最新数据跑一次策略信号，落到 PaperBroker（本地模拟盘，幂等）。"""
    import pandas as pd
    from backtest.engine import BacktestEngine
    from data.fundamentals import load_fundamentals
    from strategy.cross_asset import CrossAssetStrategy

    bars_dir = ROOT / "data" / "bars"
    etf = ["518880", "513100"]
    # 股票池：最近上市的一批标的（控制规模，200 只随机抽样即可出信号）
    stock_codes = sorted(p.stem for p in bars_dir.glob("*.parquet")
                         if p.stem not in ("518880", "513100"))
    if len(stock_codes) > 200:
        step = len(stock_codes) // 200
        stock_codes = stock_codes[::step][:200]

    from data.storage import Storage
    storage = Storage(str(DB), str(bars_dir))
    bars = {}
    for code in etf + stock_codes:
        try:
            df = storage.load_bars(code)
            if df is not None and len(df):
                # 只取最近 400 个交易日（信号不需要全历史）
                bars[code] = df.tail(400).reset_index(drop=True)
        except Exception:  # noqa: BLE001
            continue
    if "518880" not in bars or "513100" not in bars:
        log.warning("[step3] ETF 数据缺失，跳过信号")
        return True

    fundamentals = load_fundamentals()
    if fundamentals is not None and fundamentals.empty:
        fundamentals = None

    strategy = CrossAssetStrategy(lam=lam, top_n=top_n, fundamentals=fundamentals)
    engine = BacktestEngine(strategy=strategy)
    result = engine.run(bars)

    m = result.metrics
    log.info(f"[step3] 信号回放完成：收益 {m['total_return']:+.2%} | "
             f"回撤 {m['max_drawdown']:.2%} | 成交 {len(result.trades)} 笔")
    # 净值留档（Web 看板用）
    report_dir = ROOT / "report"
    report_dir.mkdir(exist_ok=True)
    eq_df = result.equity.reset_index()
    eq_df.columns = ["date", "equity"]
    eq_df.to_csv(report_dir / "equity.csv", index=False)
    return True


# ----------------------------------------------------------------------
# 主流程
# ----------------------------------------------------------------------
def run_daily_job(top_n: int = 50, lam: float = 0.5):
    """每日全流程（各环节独立 try，失败不阻断后续环节留痕）。"""
    log.info("========== 每日任务开始 ==========")
    t0 = time.time()
    for name, fn in (
        ("行情增量", lambda: step_fetch_recent()),
        ("财报增量", step_fetch_fundamentals),
        ("信号+模拟盘", lambda: step_run_signals(top_n=top_n, lam=lam)),
        ("实盘净值留痕", lambda: _step_paper_equity()),
        ("交易日报", lambda: _step_daily_report()),
    ):
        try:
            fn()
        except Exception as e:  # noqa: BLE001
            log.error(f"[daily] 环节「{name}」异常: {type(e).__name__} {str(e)[:120]}")
    log.info(f"========== 每日任务完成（{time.time() - t0:.0f}s）==========")


def _step_paper_equity() -> bool:
    """实盘净值留痕（QMT 柜台总资产 → data/paper_equity.csv，幂等）。"""
    from scripts.paper_equity import record
    msg = record()
    log.info(f"[step5] {msg}")
    return True


def _step_daily_report() -> bool:
    """交易日报（report/daily/YYYY-MM-DD.md）。"""
    from scripts.daily_report import generate
    out = generate()
    log.info(f"[step6] 日报已生成 {out.name}")
    return True


def main():
    parser = argparse.ArgumentParser(description="每日自动化调度")
    parser.add_argument("--time", default="15:30", help="每交易日执行时刻（默认 15:30）")
    parser.add_argument("--run-now", action="store_true", help="立即执行一次")
    parser.add_argument("--top-n", type=int, default=50)
    parser.add_argument("--lam", type=float, default=0.5)
    parser.add_argument("--run-fetch-recent", type=int, default=0, metavar="DAYS",
                        help="只跑环节1：增量采集最近 N 日行情后退出（看板控制台用）")
    args = parser.parse_args()

    if args.run_fetch_recent:
        ok = step_fetch_recent(args.run_fetch_recent)
        sys.exit(0 if ok else 1)

    if args.run_now:
        run_daily_job(top_n=args.top_n, lam=args.lam)
        return

    # APScheduler 定时：交易日（周一~五）指定时刻
    try:
        from apscheduler.schedulers.blocking import BlockingScheduler
    except ImportError:
        log.error("APScheduler 未安装：pip install apscheduler")
        sys.exit(1)

    hh, mm = args.time.split(":")
    sched = BlockingScheduler()

    # 交易日判断：周末不跑（节假日由 step1 幂等性天然兼容——无新数据即空跑）
    sched.add_job(
        lambda: run_daily_job(top_n=args.top_n, lam=args.lam),
        trigger="cron",
        day_of_week="mon-fri",
        hour=int(hh), minute=int(mm),
        id="daily_quant_job",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=3600,
    )

    log.info(f"[scheduler] 已启动：每交易日 {args.time} 执行（Ctrl-C 停止）")
    try:
        sched.start()
    except (KeyboardInterrupt, SystemExit):
        log.info("[scheduler] 已停止")


if __name__ == "__main__":
    main()
