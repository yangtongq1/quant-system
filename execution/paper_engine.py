"""模拟盘信号引擎（M5 执行层 · 完整版）

链路：本地数据 → 回测引擎真实重放（真实资金）→ 期末持仓 = 目标持仓
     → 与数据库现持仓求差额 → 调仓单 → 执行（SuperMind / 本地）→ 入库

与回测共用同一 Strategy + BacktestEngine（红线：回测/模拟盘共用策略代码，仅 Broker 不同）。
"""

from __future__ import annotations

import sqlite3
from datetime import datetime

import pandas as pd

from core.config import load_config
from core.logger import get_logger

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

log = get_logger("paper", log_dir=str(ROOT / "logs"))


def load_fundamentals() -> pd.DataFrame | None:
    db = ROOT / "data" / "quant.db"
    if not db.exists():
        return None
    try:
        with sqlite3.connect(str(db)) as conn:
            return pd.read_sql(
                "SELECT code, report_date, period, roe, revenue_yoy, gross_margin "
                "FROM fundamentals WHERE report_date IS NOT NULL",
                conn,
            )
    except Exception:  # noqa: BLE001
        return None


def load_current_positions() -> dict[str, float]:
    """数据库中的现持仓（volume，按 code）。"""
    db = ROOT / "data" / "quant.db"
    if not db.exists():
        return {}
    try:
        with sqlite3.connect(str(db)) as conn:
            rows = conn.execute(
                "SELECT code, volume FROM positions WHERE volume > 0"
            ).fetchall()
        return {code: float(vol) for code, vol in rows}
    except Exception:  # noqa: BLE001
        return {}


def run_paper_signals(
    broker,
    initial_cash: float = 1_000_000.0,
    top_n: int | None = None,
    lam: float | None = None,
    pool_limit: int = 400,
) -> dict:
    """跑一次模拟盘信号。

    核心思路：用 BacktestEngine 把策略真实重放到最新交易日（真实资金、
    真实成交约束），期末 PaperBroker 持仓即策略当前应该持有的目标组合；
    再与数据库中记录的现持仓求差额，生成调仓单。

    返回：{"orders", "target_positions", "n_bars", "last_date", "lam", "top_n", "equity"}
    """
    from backtest.engine import BacktestEngine
    from data.storage import Storage
    from strategy.cross_asset import CrossAssetStrategy

    cfg = load_config(ROOT / "config" / "config.yaml")
    strat_cfg = cfg.get("strategy", {}).get("cross_asset", {})
    storage = Storage(str(ROOT / "data" / "quant.db"), str(ROOT / "data" / "bars"))

    lam = lam if lam is not None else strat_cfg.get("lambda_risk", 0.5)
    top_n = top_n or strat_cfg.get("top_n", 30)

    # ── 1. 组池：ETF + 代表性股票池 ──
    bars_dir = ROOT / "data" / "bars"
    stock_codes = sorted(
        p.stem for p in bars_dir.glob("*.parquet")
        if p.stem not in ("518880", "513100")
    )
    if len(stock_codes) > pool_limit:
        stock_codes = stock_codes[:pool_limit]
    codes = ["518880", "513100"] + stock_codes

    bars = {}
    for c in codes:
        try:
            df = storage.load_bars(c)
            if df is not None and len(df) >= 250:
                bars[c] = df
        except Exception:  # noqa: BLE001
            continue
    if "518880" not in bars or "513100" not in bars:
        raise RuntimeError("行情数据不足（需 518880/513100）")

    # ── 2. 真实重放（共用回测引擎；broker 核心带真实资金）──
    fund = load_fundamentals()
    strategy = CrossAssetStrategy(
        lam=lam,
        top_n=top_n,
        stock_codes=[c for c in bars if c not in ("518880", "513100")],
        fundamentals=fund,
    )

    paper_core = getattr(broker, "paper", None)
    engine = BacktestEngine(strategy, broker=paper_core, initial_cash=initial_cash)
    result = engine.run(bars)

    # 期末持仓 = 目标持仓
    target_positions = {
        code: float(pos.volume) for code, pos in paper_core.positions.items()
        if pos.volume > 0
    }
    equity = float(result.equity.iloc[-1]) if len(result.equity) else initial_cash
    last_date = str(result.equity.index[-1].date()) if len(result.equity) else "—"

    # ── 3. 与现持仓求差额 → 调仓单 ──
    latest_close = {
        code: float(df["close"].iloc[-1] * float(df["adj_factor"].iloc[-1] or 1.0))
        for code, df in bars.items()
    }
    current = load_current_positions()

    orders = []
    all_codes = set(target_positions) | set(current)
    for code in sorted(all_codes):
        tgt = target_positions.get(code, 0.0)
        cur = current.get(code, 0.0)
        diff = tgt - cur
        price = latest_close.get(code, 0.0)
        if abs(diff) < 100 or price <= 0:
            continue
        orders.append({
            "code": code, "side": "buy" if diff > 0 else "sell",
            "volume": int(abs(diff)), "price": round(price, 3),
        })

    return {
        "orders": orders,
        "target_positions": target_positions,
        "n_bars": len(bars),
        "last_date": last_date,
        "lam": lam,
        "top_n": top_n,
        "equity": equity,
        # 重放期内全部成交流水（买入+卖出，含日期/费用）→ 入 trades 表
        "replay_trades": list(getattr(paper_core, "trades", [])),
        "trade_batch": f"RP-{datetime.now().strftime('%Y%m%d%H%M%S')}",
    }


def persist_paper_state(broker, result: dict, storage: "Storage"):
    """订单/持仓/账户快照入库（幂等：主键 OR REPLACE）+ 重放成交流水入库。"""
    now = datetime.now().isoformat(timespec="seconds")
    conn = sqlite3.connect(str(ROOT / "data" / "quant.db"))
    cur = conn.cursor()
    for i, o in enumerate(result.get("orders", [])):
        oid = f"PP-{now.replace(':', '').replace('-', '')}-{i:03d}"
        cur.execute(
            "INSERT OR REPLACE INTO orders "
            "(order_id, code, side, price, volume, status, create_time, update_time, strategy) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (oid, o["code"], o["side"], float(o.get("price", 0)),
             int(o.get("volume", 0)), "FILLED", now, now, "cross_asset"),
        )
    # 目标持仓覆盖式写入（最新快照语义）
    cur.execute("DELETE FROM positions")
    for code, vol in result.get("target_positions", {}).items():
        cur.execute(
            "INSERT OR REPLACE INTO positions (code, volume, avg_cost, market_value) "
            "VALUES (?, ?, 0, 0)",
            (code, int(vol)),
        )
    cur.execute(
        "INSERT OR REPLACE INTO accounts (account_id, cash, total_asset, update_time) "
        "VALUES (?, ?, ?, ?)",
        ("paper_local", 0.0, float(result.get("equity", 0.0)), now),
    )
    # ── 重放成交流水入库（完整买卖记录：回放期内每一笔买入/卖出）──
    # 幂等：同一次 run-paper 的批次号去重（重复执行不重复入账）
    batch = result.get("trade_batch")
    if batch:
        n = cur.execute(
            "SELECT COUNT(*) FROM trades WHERE order_id LIKE ?", (f"{batch}-%",)
        ).fetchone()[0]
        replay_trades = result.get("replay_trades") or []
        if n == 0 and replay_trades:
            for i, t in enumerate(replay_trades):
                cur.execute(
                    "INSERT OR REPLACE INTO trades "
                    "(trade_id, order_id, code, side, price, volume, fee, time) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (f"{batch}-{i:05d}", f"{batch}-{i:05d}", t["code"], t["side"],
                     float(t["price"]), int(t["volume"]), float(t.get("fee", 0)),
                     t.get("date") or now[:10]),
                )
    conn.commit()
    conn.close()
