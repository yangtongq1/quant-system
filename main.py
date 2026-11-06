"""
CLI 入口（全量子命令）

用法：
  python main.py fetch --code 600519 --start 20250101 --end 20260101   # 采集股票日线
  python main.py fetch-etf --code 518880                              # 采集 ETF（黄金/纳指）
  python main.py fetch-list                                            # 股票列表 + 交易日历
  python main.py fetch-batch --codes 600519,000001,600036             # 批量采集
  python main.py backtest --strategy dual_ma --codes 600519            # 双均线回测
  python main.py backtest --strategy cross_asset --top-n 20           # 跨资产策略回测（需先采 ETF）
  python main.py report                                               # 生成报告
  python main.py factors-qa                                           # 因子质检
  python main.py stress                                               # 压力测试
  python main.py run-paper                                            # 模拟盘（SuperMind，缺 SDK 时 DryRun）
  python main.py monitor                                              # 相关性监控
  python main.py fetch-news                                           # 知识板块 RSS 采集
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from core.config import load_config
from core.logger import get_logger

ROOT = Path(__file__).resolve().parent
log = get_logger("quant", log_dir=str(ROOT / "logs"))

CONFIG = load_config(ROOT / "config" / "config.yaml")


# ----------------------------------------------------------------------
# 数据采集
# ----------------------------------------------------------------------
def cmd_fetch(args):
    from data.cleaner import clean_daily_bars
    from data.fetcher.akshare_fetcher import AkshareFetcher
    from data.storage import Storage

    fetcher = AkshareFetcher()
    storage = Storage(str(ROOT / CONFIG["data"]["db_path"]),
                      str(ROOT / CONFIG["data"]["bars_dir"]))
    print(f"[fetch] 采集股票 {args.code} 日线（不复权价 + 复权因子）...")
    raw = fetcher.fetch_daily_bars(args.code, args.start, args.end)
    if raw is None or raw.empty:
        print(f"[fetch] {args.code} 无数据")
        return
    cleaned = clean_daily_bars(raw)
    storage.save_bars(args.code, cleaned)
    print(f"[fetch] 完成：{args.code} 共 {len(cleaned)} 条，已存 Parquet")


def cmd_fetch_etf(args):
    from data.cleaner import clean_daily_bars
    from data.fetcher.akshare_fetcher import AkshareFetcher
    from data.storage import Storage

    fetcher = AkshareFetcher()
    storage = Storage(str(ROOT / CONFIG["data"]["db_path"]),
                      str(ROOT / CONFIG["data"]["bars_dir"]))
    print(f"[fetch-etf] 采集 ETF {args.code} ...")
    raw = fetcher.fetch_etf_bars(args.code, args.start, args.end)
    if raw is None or raw.empty:
        print(f"[fetch-etf] {args.code} 无数据")
        return
    raw = raw.copy()
    raw["adj_factor"] = 1.0  # ETF 无复权（分红极少，简化处理）
    cleaned = clean_daily_bars(raw)
    storage.save_bars(args.code, cleaned)
    print(f"[fetch-etf] 完成：{args.code} 共 {len(cleaned)} 条")


def cmd_fetch_list(args):
    from data.fetcher.akshare_fetcher import AkshareFetcher
    from data.storage import Storage

    fetcher = AkshareFetcher()
    storage = Storage(str(ROOT / CONFIG["data"]["db_path"]),
                      str(ROOT / CONFIG["data"]["bars_dir"]))
    print("[fetch-list] 采集交易日历 ...")
    for attempt in range(3):
        try:
            cal = fetcher.fetch_trade_calendar(args.start, args.end)
            break
        except Exception as e:  # noqa: BLE001
            if attempt == 2:
                print(f"[fetch-list] 交易日历获取失败（跳过，不影响股票列表）: {e}")
                cal = None
            else:
                print(f"[fetch-list] 交易日历重试 {attempt + 1} ...")
    if cal is not None:
        storage.save_calendar(cal)
        print(f"[fetch-list] 交易日历 {len(cal)} 条")

    print("[fetch-list] 采集股票列表（含退市）...")
    stocks = fetcher.fetch_stock_list()
    storage.save_stocks(stocks)
    n_listed = int((stocks["status"] == "listed").sum())
    n_delisted = int((stocks["status"] == "delisted").sum())
    print(f"[fetch-list] 股票列表 {len(stocks)} 条（存续 {n_listed} / 退市 {n_delisted}）")


def cmd_fetch_batch(args):
    """批量采集多只股票。"""
    from data.cleaner import clean_daily_bars
    from data.fetcher.akshare_fetcher import AkshareFetcher
    from data.storage import Storage

    fetcher = AkshareFetcher()
    storage = Storage(str(ROOT / CONFIG["data"]["db_path"]),
                      str(ROOT / CONFIG["data"]["bars_dir"]))
    codes = [c.strip() for c in args.codes.split(",") if c.strip()]
    ok, fail = 0, 0
    for code in codes:
        try:
            raw = fetcher.fetch_daily_bars(code, args.start, args.end)
            if raw is None or raw.empty:
                print(f"[fetch-batch] {code} 无数据")
                fail += 1
                continue
            cleaned = clean_daily_bars(raw)
            storage.save_bars(code, cleaned)
            print(f"[fetch-batch] {code}: {len(cleaned)} 条")
            ok += 1
        except Exception as e:  # noqa: BLE001
            print(f"[fetch-batch] {code} 失败: {e}")
            fail += 1
    print(f"[fetch-batch] 完成：成功 {ok} / 失败 {fail}")


# ----------------------------------------------------------------------
# 回测
# ----------------------------------------------------------------------
def _load_bars(codes: list[str]) -> dict[str, pd.DataFrame]:
    """从本地 Parquet 加载多标的日线。"""
    from data.storage import Storage

    storage = Storage(str(ROOT / CONFIG["data"]["db_path"]),
                      str(ROOT / CONFIG["data"]["bars_dir"]))
    bars = {}
    for code in codes:
        try:
            df = storage.load_bars(code)
            if df is not None and len(df):
                bars[code] = df
        except Exception:  # noqa: BLE001
            continue
    return bars


def _make_strategy(args):
    if args.strategy == "dual_ma":
        from strategy.examples.dual_ma import DualMAStrategy
        return DualMAStrategy(fast=args.fast, slow=args.slow)
    if args.strategy == "cross_asset":
        from strategy.cross_asset import CrossAssetStrategy
        strat_cfg = CONFIG.get("strategy", {})
        # 优先级：命令行显式传参 > config.yaml（默认值 -1 表示「未显式指定」）
        lam = args.lam if getattr(args, "lam", -1) >= 0 else strat_cfg.get("lambda_risk", 0.5)

        # 基本面数据注入（point-in-time 选股增强；库为空则纯价量模式）
        fundamentals = None
        if not getattr(args, "no_fundamentals", False):
            from data.fundamentals import load_fundamentals
            fundamentals = load_fundamentals()
            if fundamentals is None or fundamentals.empty:
                print("[backtest] fundamentals 表为空，选股用纯价量模式")
                fundamentals = None

        return CrossAssetStrategy(
            lam=lam,
            top_n=args.top_n or strat_cfg.get("stock_universe", 50),
            fundamentals=fundamentals,
        )
    print(f"[backtest] 未知策略: {args.strategy}（可选 dual_ma / cross_asset）")
    return None


def _backtest_codes(args) -> list[str]:
    if args.codes:
        return [c.strip() for c in args.codes.split(",") if c.strip()]
    if args.strategy == "cross_asset":
        # 动态股票池：全部已入库标的（指数成分股已优先采集）+ 两只 ETF
        bars_dir = ROOT / "data" / "bars"
        all_codes = sorted(p.stem for p in bars_dir.glob("*.parquet"))
        if not all_codes:
            return ["518880", "513100"]
        pool = [c for c in all_codes if c not in ("518880", "513100")]
        return ["518880", "513100"] + pool
    return ["600519"]


def cmd_backtest(args):
    from backtest.engine import BacktestEngine

    strategy = _make_strategy(args)
    if strategy is None:
        return

    codes = _backtest_codes(args)
    bars = _load_bars(codes)
    if not bars:
        print(f"[backtest] 本地无行情数据：{codes}")
        print("[backtest] 先运行: python main.py fetch-etf --code 518880 等采集命令")
        return

    print(f"[backtest] 策略={args.strategy}，标的 {len(bars)} 只，资金 {args.cash:,.0f}")
    engine = BacktestEngine(strategy=strategy, initial_cash=args.cash)
    result = engine.run(bars)

    m = result.metrics
    print("\n========== 回测结果 ==========")
    print(f"累计收益: {m['total_return']:+.2%} | 年化: {m['annual_return']:+.2%}")
    print(f"最大回撤: {m['max_drawdown']:.2%} | 夏普: {m['sharpe']:.3f} | 卡玛: {m['calmar']:.3f}")
    print(f"成交笔数: {len(result.trades)}")
    print("==============================\n")

    # 缓存净值 + 自动生成报告
    report_dir = ROOT / "report"
    report_dir.mkdir(exist_ok=True)
    eq_df = result.equity.reset_index()
    eq_df.columns = ["date", "equity"]
    eq_df.to_csv(report_dir / "equity.csv", index=False)
    _generate_report_files(result, title=f"{args.strategy} 回测报告")


# ----------------------------------------------------------------------
# 报告生成
# ----------------------------------------------------------------------
def _generate_report_files(result, title: str = "回测报告"):
    from report.charts import plot_drawdown, plot_equity_curves, plot_monthly_returns_heatmap
    from report.performance import generate_report

    report_dir = ROOT / "report"
    report_dir.mkdir(exist_ok=True)

    charts = {}
    try:
        p1 = plot_equity_curves({"策略": result.equity}, out_path=report_dir / "equity.png")
        p2 = plot_drawdown(result.equity, out_path=report_dir / "drawdown.png")
        charts = {"净值曲线": p1, "回撤曲线": p2}
        try:
            p3 = plot_monthly_returns_heatmap(result.equity, out_path=report_dir / "monthly.png")
            charts["月度收益热力图"] = p3
        except Exception as e:  # noqa: BLE001
            print(f"[report] 月度热力图跳过: {e}")
    except Exception as e:  # noqa: BLE001
        print(f"[report] 图表生成失败（不影响报告）: {e}")

    out = generate_report(result.equity, trades=result.trades, title=title,
                          out_path=report_dir / "report.md", chart_paths=charts)
    print(f"[report] 报告已生成: {out}")


def cmd_report(args):
    """从最近回测净值重生成报告（净值缓存 report/equity.csv）。"""
    eq_file = ROOT / "report" / "equity.csv"
    if not eq_file.exists():
        print("[report] 无缓存净值（report/equity.csv）。先运行 backtest。")
        return
    df = pd.read_csv(eq_file, parse_dates=["date"], index_col="date")
    from backtest.engine import BacktestResult
    from backtest.metrics import compute_metrics
    result = BacktestResult(equity=df["equity"], trades=[],
                            metrics=compute_metrics(df["equity"]))
    _generate_report_files(result, title="绩效报告")


# ----------------------------------------------------------------------
# 因子质检 / 压力测试 / 模拟盘 / 监控
# ----------------------------------------------------------------------
def cmd_factors_qa(args):
    from factors.engine import FactorEngine
    from factors.qa import qa_report

    codes = [c.strip() for c in args.codes.split(",") if c.strip()]
    bars = _load_bars(codes)
    if len(bars) < 3:
        print("[factors-qa] 本地行情不足 3 只（质检需截面），先采集多只股票")
        return

    engine = FactorEngine(bars)
    panels = engine.compute_all()
    # 下期收益面板
    rets = {c: (df["close"] * df["adj_factor"]).pct_change().shift(-1)
            for c, df in bars.items()}
    ret_panel = pd.DataFrame({c: s for c, s in rets.items()})

    qa_dir = ROOT / "report" / "qa"
    qa_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    existing: dict = {}
    for name, panel in panels.items():
        if panel.empty:
            continue
        rep = qa_report(panel, ret_panel, existing=existing or None)
        existing[name] = panel
        rows.append({
            "factor": name,
            "ic_mean": round(rep["ic_mean"], 4) if pd.notna(rep["ic_mean"]) else None,
            "icir": round(rep["icir"], 4) if pd.notna(rep["icir"]) else None,
            "ic_win_rate": round(rep["ic_win_rate"], 4) if pd.notna(rep["ic_win_rate"]) else None,
            "coverage": round(rep["coverage"], 4),
            "monotonicity": round(rep["monotonicity"], 4) if pd.notna(rep["monotonicity"]) else None,
            "corr_alerts": rep["corr_alerts"],
        })
        print(f"[factors-qa] {name}: IC={rows[-1]['ic_mean']} ICIR={rows[-1]['icir']}")
    df = pd.DataFrame(rows)
    df.to_csv(qa_dir / "qa_summary.csv", index=False, encoding="utf-8-sig")
    print(f"[factors-qa] 质检汇总已存 {qa_dir / 'qa_summary.csv'}")


def _three_asset_prices() -> pd.DataFrame | None:
    """构造三资产价格表（需 518880/513100 + 至少 1 只股票）。"""
    etf_bars = _load_bars(["518880", "513100"])
    stock_bars = _load_bars(["600519", "000001", "601318"])
    if len(etf_bars) < 2 or not stock_bars:
        return None
    gold = etf_bars["518880"].set_index(pd.to_datetime(etf_bars["518880"]["date"]))["close"]
    nasdaq = etf_bars["513100"].set_index(pd.to_datetime(etf_bars["513100"]["date"]))["close"]
    stock = pd.concat(
        [b.set_index(pd.to_datetime(b["date"]))["close"] for b in stock_bars.values()],
        axis=1,
    ).mean(axis=1)
    return pd.DataFrame({"stock": stock, "gold": gold, "nasdaq": nasdaq}).dropna()


def cmd_stress(args):
    from risk.stress import full_stress_report

    prices = _three_asset_prices()
    if prices is None:
        print("[stress] 需先采集 ETF（518880/513100）与股票数据（fetch-etf / fetch）")
        return

    eq_file = ROOT / "report" / "equity.csv"
    equity = None
    if eq_file.exists():
        df = pd.read_csv(eq_file, parse_dates=["date"], index_col="date")
        equity = df["equity"]

    report = full_stress_report(equity if equity is not None else prices["stock"], prices)
    out = ROOT / "report"
    report["scenario_replay"].to_csv(out / "stress_test.csv", index=False, encoding="utf-8-sig")
    report["hedge_failure"].to_csv(out / "hedge_failure.csv", index=False, encoding="utf-8-sig")
    print("[stress] 情景回放：")
    print(report["scenario_replay"].to_string(index=False))
    print("\n[stress] 对冲失效测试：")
    print(report["hedge_failure"].to_string(index=False))
    print(f"\n[stress] 已存 {out / 'stress_test.csv'} 与 {out / 'hedge_failure.csv'}")


def cmd_run_paper(args):
    """模拟盘：策略重放 → 期末目标持仓 → 差额调仓单 → 执行入库。"""
    from execution.paper_broker import PaperBrokerAdapter
    from execution.paper_engine import persist_paper_state, run_paper_signals
    from execution.supermind_broker import SuperMindBroker

    use_supermind = getattr(args, "supermind", False)
    if use_supermind:
        broker = SuperMindBroker()
        if broker.dry_run:
            print("[run-paper] SuperMind 不可用（未装 SDK/未配置账号），回退本地 PaperBroker。")
            use_supermind = False
    if not use_supermind:
        broker = PaperBrokerAdapter(initial_cash=1_000_000.0)

    print(f"[run-paper] 执行器：{'SuperMind' if use_supermind else '本地 PaperBroker'}"
          f"（dry_run={getattr(broker, 'dry_run', False)}）")

    result = run_paper_signals(
        broker,
        top_n=getattr(args, "top_n", None) or 30,
        lam=getattr(args, "lam", None) if getattr(args, "lam", -1) >= 0 else None,
    )

    from data.storage import Storage
    storage = Storage(str(ROOT / "data" / "quant.db"), str(ROOT / "data" / "bars"))
    persist_paper_state(broker, result, storage)

    print(f"[run-paper] 重放至 {result['last_date']}（λ={result['lam']} top{result['top_n']}，"
          f"池 {result['n_bars']} 只，期末净值 {result['equity']:,.0f}）")
    print(f"[run-paper] 目标持仓 {len(result['target_positions'])} 只，调仓单 {len(result['orders'])} 笔：")
    for o in result["orders"]:
        print(f"    {o['side']:4s} {o['code']} {o['volume']} @ {o['price']:.3f}")
    if not result["orders"]:
        print("    （目标持仓与现持仓一致，无调仓）")
    print("[run-paper] 订单/持仓已入库 data/quant.db")


def cmd_monitor(args):
    """相关性监控（分散失效检测）。"""
    from risk.correlation_monitor import CorrelationMonitor

    prices = _three_asset_prices()
    if prices is None:
        print("[monitor] 需先采集 ETF（518880/513100）与股票数据（fetch-etf / fetch）")
        return
    mon = CorrelationMonitor()
    result = mon.check_latest(prices)
    out = ROOT / "report" / "correlation.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[monitor] {result['date']} 黄金-A股相关 {result.get('gold_stock_corr')} | "
          f"纳指-A股相关 {result.get('nasdaq_stock_corr')} | 状态 {result['status']}")
    for a in result.get("alerts", []):
        print(f"  ⚠️ {a}")
    print(f"[monitor] 已存 {out}")


# ----------------------------------------------------------------------
# 知识板块
# ----------------------------------------------------------------------
def cmd_fetch_news(args):
    from knowledge.fetcher.rss_fetcher import RssFetcher
    from knowledge.storage import KnowledgeStorage
    from knowledge.translator import summarize_zh, translate

    sources = ROOT / CONFIG["data"].get("sources_yaml", "knowledge/sources.yaml")
    kb = KnowledgeStorage(ROOT / CONFIG["data"].get("knowledge_db", "knowledge/knowledge.db"))
    fetcher = RssFetcher(sources)

    print("[fetch-news] 抓取 RSS 源 ...")
    df = fetcher.fetch_all()
    if df.empty:
        print("[fetch-news] 未抓到文章（网络/代理问题，国外源需代理）")
        return
    print(f"[fetch-news] 抓取 {len(df)} 条")

    if args.translate:
        print("[fetch-news] LLM 翻译（需 ZHIPU_API_KEY，未配置则跳过）...")
        import os
        if not os.environ.get("ZHIPU_API_KEY"):
            print("[fetch-news] ZHIPU_API_KEY 未配置，跳过翻译")
        else:
            n = min(len(df), args.max_translate)
            for i in range(n):
                try:
                    df.at[i, "title_zh"] = translate(str(df.at[i, "title"]))
                    df.at[i, "summary_zh"] = summarize_zh(str(df.at[i, "summary"])[:500])
                except Exception:  # noqa: BLE001
                    continue
            print(f"[fetch-news] 翻译 {n} 条")

    kb.upsert_articles(df)
    print("[fetch-news] 入库完成（link 去重）")


# ----------------------------------------------------------------------
# 参数解析
# ----------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="量化系统 CLI")
    sub = parser.add_subparsers(dest="cmd")

    p = sub.add_parser("fetch")
    p.add_argument("--code", required=True)
    p.add_argument("--start", default="20250101")
    p.add_argument("--end", default="20261231")
    p.set_defaults(func=cmd_fetch)

    p = sub.add_parser("fetch-etf")
    p.add_argument("--code", required=True)
    p.add_argument("--start", default="20200101")
    p.add_argument("--end", default="20261231")
    p.set_defaults(func=cmd_fetch_etf)

    p = sub.add_parser("fetch-list")
    p.add_argument("--start", default="20200101")
    p.add_argument("--end", default="20261231")
    p.set_defaults(func=cmd_fetch_list)

    p = sub.add_parser("fetch-batch")
    p.add_argument("--codes", required=True)
    p.add_argument("--start", default="20240101")
    p.add_argument("--end", default="20261231")
    p.set_defaults(func=cmd_fetch_batch)

    p = sub.add_parser("backtest")
    p.add_argument("--strategy", default="dual_ma", choices=["dual_ma", "cross_asset"])
    p.add_argument("--codes", default="")
    p.add_argument("--start", default="20240101")
    p.add_argument("--end", default="20261231")
    p.add_argument("--cash", type=float, default=1_000_000)
    p.add_argument("--fast", type=int, default=5)
    p.add_argument("--slow", type=int, default=20)
    p.add_argument("--lam", type=float, default=-1,
                   help="风险档位 λ（0.1 稳健/0.5 平衡/0.9 进取；不传则用 config.yaml 的 lambda_risk）")
    p.add_argument("--top-n", type=int, default=0)
    p.add_argument("--no-fundamentals", action="store_true",
                   help="选股不注入基本面因子（纯价量模式）")
    p.set_defaults(func=cmd_backtest)

    p = sub.add_parser("report")
    p.set_defaults(func=cmd_report)

    p = sub.add_parser("factors-qa")
    p.add_argument("--codes", default="600519,000858,601318,600036,000001,600276")
    p.set_defaults(func=cmd_factors_qa)

    p = sub.add_parser("stress")
    p.set_defaults(func=cmd_stress)

    p = sub.add_parser("run-paper")
    p.add_argument("--supermind", action="store_true", help="用 SuperMind 仿真盘（默认本地 PaperBroker）")
    p.add_argument("--top-n", type=int, default=30, help="持股数")
    p.add_argument("--lam", type=float, default=-1, help="风险档位 λ（0.1/0.5/0.9）")
    p.set_defaults(func=cmd_run_paper)

    p = sub.add_parser("monitor")
    p.set_defaults(func=cmd_monitor)

    p = sub.add_parser("fetch-news")
    p.add_argument("--translate", action="store_true")
    p.add_argument("--max-translate", type=int, default=20)
    p.set_defaults(func=cmd_fetch_news)

    args = parser.parse_args()
    if not getattr(args, "func", None):
        parser.print_help()
        return
    args.func(args)


if __name__ == "__main__":
    main()
