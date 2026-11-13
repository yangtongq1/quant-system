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


def load_stock_meta() -> pd.DataFrame | None:
    """股票元数据（stocks 表：board/is_st/status/delist_date）——稳健过滤用。"""
    db = ROOT / "data" / "quant.db"
    if not db.exists():
        return None
    try:
        with sqlite3.connect(str(db)) as conn:
            return pd.read_sql(
                "SELECT code, name, board, is_st, status, delist_date FROM stocks",
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


def load_strategy_order_codes() -> set[str]:
    """策略历史订单涉及的全部代码（orders 表）——「策略管理范围」依据。

    柜台（QMT）持仓混有用户自有仓位（如 510300 两百万股）：代码从未
    出现在策略订单历史 → 非策略持仓，差额计算绝不触碰。
    """
    db = ROOT / "data" / "quant.db"
    if not db.exists():
        return set()
    try:
        with sqlite3.connect(str(db)) as conn:
            rows = conn.execute("SELECT DISTINCT code FROM orders").fetchall()
        return {r[0] for r in rows if r[0]}
    except Exception:  # noqa: BLE001
        return set()


def _fallback_price(code: str) -> float:
    """无本地行情（bars 缺失）标的的兜底价：QMT 实时行情 → 台账成本价。

    场景：管理范围内持仓被数据层过滤（ST/退市股无 parquet）→
    latest_close 缺失 → 差额段 price=0 静默跳过 → 清仓卖单永远生成不了。
    """
    # 1) QMT 实时行情（有 xtquant 时）
    try:
        from xtquant import xtdata

        if code.startswith(("6", "9", "5")):
            sym = f"{code}.SH"
        elif code.startswith(("0", "3", "1")):
            sym = f"{code}.SZ"
        else:
            sym = f"{code}.BJ"
        tick = xtdata.get_full_tick([sym]) or {}
        d = tick.get(sym) or {}
        if d:
            ask1 = (d.get("askPrice") or [0])[0]
            bid1 = (d.get("bidPrice") or [0])[0]
            last = d.get("lastPrice") or 0
            px = float(ask1 or bid1 or last or 0)
            if px > 0:
                return px
    except Exception:  # noqa: BLE001
        pass
    # 2) DB 台账成本价（最后兜底：QMT 不在线/无行情）
    try:
        db = ROOT / "data" / "quant.db"
        if db.exists():
            with sqlite3.connect(str(db)) as conn:
                row = conn.execute(
                    "SELECT avg_cost FROM positions WHERE code=?", (code,)
                ).fetchone()
            if row and row[0] and float(row[0]) > 0:
                return float(row[0])
    except Exception:  # noqa: BLE001
        pass
    return 0.0


def reset_current_positions() -> None:
    """清空数据库现持仓（首跑建仓用：差额 = 目标持仓全量买入）。"""
    db = ROOT / "data" / "quant.db"
    if not db.exists():
        return
    with sqlite3.connect(str(db)) as conn:
        conn.execute("DELETE FROM positions")
        conn.commit()


# ETF 腿风控规则：放宽单标的/单笔上限（黄金/纳指目标权重 10%~70%，动态权重
# 裁剪范围），个股维持默认严规则（max_position_pct=0.20 / max_order_pct=0.05）。
def _etf_risk_rules(base: "RiskRules", strict_etf: bool = False) -> "RiskRules":
    from risk.manager import RiskRules
    if strict_etf:
        return base
    return RiskRules(
        max_position_pct=0.75,   # ETF 权重裁剪上限 70%，留缓冲
        max_order_pct=0.80,     # ETF 单腿调仓可达总资产的 70%
        max_drawdown=base.max_drawdown,
        max_single_stock_pct=base.max_single_stock_pct,
        price_deviation=base.price_deviation,
        max_orders_per_day=base.max_orders_per_day,
    )


def _now_date() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _pos_fields(p) -> tuple[str, int, int, float]:
    """持仓对象/字典统一抽取（code, volume, available, avg_cost）。

    兼容两种形态：xtquant 持仓对象（stock_code/volume/can_use_volume）
    与本地 dict（code/volume/available）。
    """
    code = getattr(p, "stock_code", None) or getattr(p, "code", None)
    if not code and isinstance(p, dict):
        code = p.get("stock_code") or p.get("code")
    vol = getattr(p, "volume", None)
    if vol is None and isinstance(p, dict):
        vol = p.get("volume")
    can = getattr(p, "can_use_volume", None)
    if can is None:
        can = getattr(p, "available", None)
    if can is None and isinstance(p, dict):
        can = p.get("can_use_volume", p.get("available"))
    cost = getattr(p, "open_price", None) or getattr(p, "avg_cost", None)
    if cost is None and isinstance(p, dict):
        cost = p.get("avg_cost", 0)
    code = str(code or "").split(".")[0]
    return code, int(vol or 0), int(can or 0), float(cost or 0)


def run_paper_signals(
    broker,
    initial_cash: float = 1_000_000.0,
    top_n: int | None = None,
    lam: float | None = None,
    pool_limit: int = 0,
    target_capital: float = 0.0,
    current_positions: dict[str, float] | None = None,
    strategy: str = "cross_asset",
) -> dict:
    """跑一次模拟盘信号。

    strategy：cross_asset（默认）/ equal_weight / risk_parity / stock_only /
    etf_momentum（strategy/multi.py 多策略体系）。

    核心思路：用 BacktestEngine 把策略真实重放到最新交易日（真实资金、
    真实成交约束），期末 PaperBroker 持仓即策略当前应该持有的目标组合；
    再与现持仓求差额，生成调仓单。

    current_positions：现持仓基准。None → 读 DB 台账；外部通道模式传
    柜台实际持仓（QMT query_stock_positions）——柜台是事实源，台账
    漂移（废单虚增）自动纠正。差额仅覆盖策略池内标的（池外持仓=
    用户自有，策略不动）。

    pool_limit=0 表示全池（与回测一致，保证模拟盘目标持仓 = 回测策略持仓）；
    传正整数则截取前 N 只（调试用，快但与回测池不一致）。

    target_capital>0：期末目标持仓等比缩放到指定资金规模（如 100 万），
    权重结构不变、手数重取整——实盘资金≠回测资金时的正确落地方式。

    返回：{"orders", "target_positions", "n_bars", "last_date", "lam", "top_n", "equity"}
    """
    from backtest.engine import BacktestEngine
    from data.storage import Storage
    from strategy.cross_asset import CrossAssetStrategy

    cfg = load_config(ROOT / "config" / "config.yaml")
    strat_cfg = cfg.get("strategy", {}).get("cross_asset", {}) or cfg.get("strategy", {})
    storage = Storage(str(ROOT / "data" / "quant.db"), str(ROOT / "data" / "bars"))

    lam = lam if lam is not None else strat_cfg.get("lambda_risk", 0.5)
    top_n = top_n or strat_cfg.get("top_n", 30)

    # ── 1. 组池：ETF + 全市场股票池（与回测一致；pool_limit>0 仅调试用）──
    # ETF 动量轮动只跑 3 只 ETF，无需全池
    if strategy == "etf_momentum":
        codes = ["518880", "513100", "510300"]
    else:
        bars_dir = ROOT / "data" / "bars"
        stock_codes = sorted(
            p.stem for p in bars_dir.glob("*.parquet")
            if p.stem not in ("518880", "513100")
        )
        if pool_limit and len(stock_codes) > pool_limit:
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
    if strategy == "etf_momentum":
        from strategy.multi import ETFMomentumStrategy
        strategy_obj = ETFMomentumStrategy()
    else:
        if strategy == "cross_asset":
            strategy_obj = CrossAssetStrategy(
                lam=lam,
                top_n=top_n,
                stock_codes=[c for c in bars if c not in ("518880", "513100")],
                fundamentals=fund,
                allow_chinext=bool(strat_cfg.get("allow_chinext", True)),
                allow_star=bool(strat_cfg.get("allow_star", True)),
                main_board_only=bool(strat_cfg.get("main_board_only", False)),
                exclude_st=bool(strat_cfg.get("exclude_st", True)),
                stock_meta=load_stock_meta(),
                rebalance_freq=str(strat_cfg.get("rebalance_freq", "monthly")),
                select_refresh_days=int(strat_cfg.get("select_refresh_days", 5)),
                max_buy_2d_pct=float(cfg.get("risk", {}).get("max_buy_2d_pct", 0) or 0),
            )
        else:
            # 多策略体系（strategy/multi.py）：继承 CrossAsset 基建，
            # 自带基准权重/λ 覆写（等权 1/3、风险平价 λ=1、纯股票 stock=1）
            from strategy.multi import (EqualWeightStrategy, RiskParityStrategy,
                                        StockOnlyStrategy)
            cls = {"equal_weight": EqualWeightStrategy,
                   "risk_parity": RiskParityStrategy,
                   "stock_only": StockOnlyStrategy}[strategy]
            strategy_obj = cls(
                top_n=top_n,
                stock_codes=[c for c in bars if c not in ("518880", "513100")],
                fundamentals=fund,
                allow_chinext=bool(strat_cfg.get("allow_chinext", True)),
                allow_star=bool(strat_cfg.get("allow_star", True)),
                main_board_only=bool(strat_cfg.get("main_board_only", False)),
                exclude_st=bool(strat_cfg.get("exclude_st", True)),
                stock_meta=load_stock_meta(),
                rebalance_freq=str(strat_cfg.get("rebalance_freq", "monthly")),
                select_refresh_days=int(strat_cfg.get("select_refresh_days", 5)),
                max_buy_2d_pct=float(cfg.get("risk", {}).get("max_buy_2d_pct", 0) or 0),
            )

    paper_core = getattr(broker, "paper", None)
    engine = BacktestEngine(strategy_obj, broker=paper_core, initial_cash=initial_cash)
    result = engine.run(bars)

    # 期末持仓 = 目标持仓
    target_positions = {
        code: float(pos.volume) for code, pos in paper_core.positions.items()
        if pos.volume > 0
    }
    equity = float(result.equity.iloc[-1]) if len(result.equity) else initial_cash
    last_date = str(result.equity.index[-1].date()) if len(result.equity) else "—"

    # ── 2.5 资金规模缩放（实盘资金 ≠ 回测资金时）──
    # 例：回测从 100 万滚到 178 万，但实盘只做 100 万 → 期末持仓等比缩放，
    # 权重结构不变，手数重取整（100 股整数）。
    if target_capital > 0 and equity > 0:
        scale = target_capital / equity
        target_positions = {
            code: float(int(vol * scale / 100) * 100)
            for code, vol in target_positions.items()
        }
        target_positions = {c: v for c, v in target_positions.items() if v > 0}

    # ── 3. 与现持仓求差额 → 调仓单 ──
    # 订单价格用「不复权真实价」（真实委托发往 QMT/掘金柜台，真实价撮合；
    # 后复权价只用于策略内部因子计算——两套口径，绝不混淆）
    latest_close = {
        code: float(df["close"].iloc[-1])
        for code, df in bars.items()
    }
    # 补价：管理范围内持仓但无 bars 数据的标的（如 ST/退市股被数据层
    # 过滤，parquet 缺失）——不补价则 price=0 被静默跳过，清仓卖单
    # 永远无法生成，持仓烂在柜台（红线 bug）。兜底链：
    # QMT 实时行情 → DB 台账成本价 → 0（无价不发单，防误操作）
    if current_positions:
        missing = [c for c in current_positions if c not in latest_close]
        for c in missing:
            px = _fallback_price(c)
            if px > 0:
                latest_close[c] = px
                log.info(f"补价：{c} 无本地行情，兜底价 {px:.3f}（清仓卖单仍可生成）")
    if current_positions is not None:
        # 外部通道模式：柜台实际持仓 = 事实源，但仅取「策略管理范围」内标的。
        # 管理范围 = 目标持仓 ∪ 策略历史订单代码（orders 表）∪ DB 台账代码。
        # 柜台混有用户自有持仓（如 510300 两百万股）——不在管理范围，绝不触碰。
        # TODO: 若用户自有与策略持仓同代码混合，卖出上限需按策略台账量截断
        managed = (set(target_positions) | set(load_current_positions())
                   | load_strategy_order_codes())
        current = {str(c): float(v) for c, v in current_positions.items()
                   if v > 0 and str(c) in managed}
    else:
        current = load_current_positions()

    orders = []
    for code in sorted(set(target_positions) | set(current)):
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


def persist_paper_state(broker, result: dict, storage: "Storage", exec_report: list | None = None,
                        channel_positions: list | None = None):
    """订单/持仓/账户快照入库（幂等：主键 OR REPLACE）+ 重放成交流水入库。

    exec_report：外部通道（QMT/掘金/SuperMind）执行报告——订单状态写
    SUBMITTED/REJECTED（真实委托语义）而非本地撮合的 FILLED。

    channel_positions：外部通道实际持仓对象列表（QMT query_stock_positions
    原始返回）。传入时执行后按柜台实际持仓修正 DB 台账（策略管理范围内）：
    废单/撤单/未成交导致的台账漂移每次 run 自动对齐，柜台 = 事实源。
    """
    now = datetime.now().isoformat(timespec="seconds")
    conn = sqlite3.connect(str(ROOT / "data" / "quant.db"))
    cur = conn.cursor()
    # 外部通道执行状态（code+side 匹配；无报告则本地语义 FILLED）
    exec_status = {}
    if exec_report:
        for r in exec_report:
            exec_status[(r["code"], r["side"])] = (r["status"], r.get("reason", ""))
    for i, o in enumerate(result.get("orders", [])):
        oid = f"PP-{now.replace(':', '').replace('-', '')}-{i:03d}"
        status, reason = exec_status.get((o["code"], o["side"]), ("FILLED", ""))
        if reason:
            status = f"{status}:{reason[:60]}"
        cur.execute(
            "INSERT OR REPLACE INTO orders "
            "(order_id, code, side, price, volume, status, create_time, update_time, strategy) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (oid, o["code"], o["side"], float(o.get("price", 0)),
             int(o.get("volume", 0)), status, now, now, "cross_asset"),
        )
    # 持仓写入：外部通道模式按柜台实际持仓修正（策略管理范围内），
    # 柜台 = 事实源——废单/未成交台账漂移每次 run 自动对齐
    if channel_positions is not None:
        managed = (set(result.get("target_positions", {}))
                   | load_strategy_order_codes())
        ch_pos = {}
        for p in channel_positions:
            code, vol, can, cost = _pos_fields(p)
            if vol > 0 and code in managed:
                ch_pos[code] = (int(vol), float(cost))
        cur.execute("DELETE FROM positions")
        for code, (vol, cost) in ch_pos.items():
            cur.execute(
                "INSERT OR REPLACE INTO positions (code, volume, avg_cost, market_value) "
                "VALUES (?, ?, ?, 0)",
                (code, vol, cost),
            )
    else:
        # 目标持仓覆盖式写入（最新快照语义）
        cur.execute("DELETE FROM positions")
        for code, vol in result.get("target_positions", {}).items():
            cur.execute(
                "INSERT OR REPLACE INTO positions (code, volume, avg_cost, market_value) "
                "VALUES (?, ?, 0, 0)",
                (code, int(vol)),
            )
    if channel_positions is not None:
        # 通道模式：账户快照写柜台真实资产
        try:
            acc = broker.get_account()
            ch_cash = float(acc.get("available_cash") or 0.0)
            ch_total = float(acc.get("total_value") or acc.get("total_asset") or 0.0)
        except Exception:  # noqa: BLE001
            ch_cash, ch_total = 0.0, float(result.get("equity", 0.0))
        cur.execute(
            "INSERT OR REPLACE INTO accounts (account_id, cash, total_asset, update_time) "
            "VALUES (?, ?, ?, ?)",
            ("paper_local", ch_cash, ch_total, now),
        )
    else:
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


def execute_orders_on_channel(
    broker,
    orders: list[dict],
    risk_manager,
    base_rules,
    etf_codes: tuple[str, ...] = ("518880", "513100"),
    price_buffer: float = 0.01,
    use_live_quotes: bool = True,
) -> list[dict]:
    """把调仓单发往外部通道（QMT/掘金/SuperMind）真实委托。

    执行顺序：先卖后买（卖出回笼资金供买入）。
    风控路由：ETF 腿（518880/513100）用放宽规则（权重 10%~70% 属策略
    设计），个股用默认严规则；每单事前校验（红线：真实委托前强制风控）。
    限价单：重放收盘价 ± price_buffer 缓冲（防开盘跳空废单）。

    返回执行报告 [{code, side, volume, price, status, reason}]。
    """
    from risk.manager import RiskManager, RiskRules  # noqa: F401

    report: list[dict] = []
    if not orders:
        return report

    etf_rules = _etf_risk_rules(base_rules)
    etf_set = set(etf_codes)

    # 组合视图（动态更新：卖出后资金回笼计入可买额度）
    def portfolio_view() -> dict:
        acc = broker.get_account()
        cash = float(acc.get("available_cash") or acc.get("cash") or 0.0)
        total = float(acc.get("total_value") or acc.get("total_asset") or 0.0)
        if total <= 0:
            total = cash
        positions = {}
        for p in broker.get_positions():
            # _pos_fields 兼容 xtquant 对象与 dict 两种形态
            code, vol, can, cost = _pos_fields(p)
            if not code:
                continue
            positions[code] = {"volume": vol, "available": can, "avg_cost": cost}
        return {"cash": cash, "total_asset": max(total, cash), "positions": positions}

    sells = [o for o in orders if o["side"] == "sell"]
    buys = [o for o in orders if o["side"] == "buy"]

    # ── 实时行情覆盖（防隔日价格漂移：重放收盘价与今日实价可能差 3-5%，──
    # ── 旧价+1% 缓冲的限价根本买不进；有实时行情源时用对手价）──
    live_prices: dict[str, float] = {}
    if use_live_quotes:
        try:
            from xtquant import xtdata

            def _sym(code: str) -> str:
                if code.startswith(("6", "9", "5")):
                    return f"{code}.SH"
                if code.startswith(("0", "3", "1")):
                    return f"{code}.SZ"
                return f"{code}.BJ"

            syms = [_sym(o["code"]) for o in orders]
            ticks = xtdata.get_full_tick(syms) or {}
            for sym, d in ticks.items():
                if not d:
                    continue
                code = sym.split(".")[0]
                ask1 = (d.get("askPrice") or [0])[0]
                bid1 = (d.get("bidPrice") or [0])[0]
                last = d.get("lastPrice") or 0
                # 通用参考价：优先盘口，退化到最新价
                live_prices[code] = float(ask1 or bid1 or last or 0)
        except ImportError:
            pass  # 无 xtquant（掘金/SuperMind 通道）：沿用重放价

    for order in sells + buys:
        code, side, volume = order["code"], order["side"], int(order["volume"])
        ref_price = float(live_prices.get(code) or order.get("price", 0) or 0)
        # ── 卖出量按柜台可用量截断（T+1：当日买入不可卖）──
        # 柜台无可用持仓（can_use=0）：跳过——不再发必废的卖单（历史废单根因）
        if side == "sell":
            try:
                avail = portfolio_view()["positions"].get(code, {}).get("available", 0)
            except Exception:  # noqa: BLE001
                avail = 0
            if avail <= 0:
                report.append({
                    "code": code, "side": side, "volume": volume, "price": 0.0,
                    "status": "SKIPPED",
                    "reason": "柜台无可用持仓（can_use=0，台账漂移自动纠正）",
                })
                continue
            if volume > avail:
                report.append({
                    "code": code, "side": side, "volume": volume, "price": 0.0,
                    "status": "SKIPPED",
                    "reason": f"卖出量 {volume} 超可用 {avail}（T+1 锁定）→ 截断为 {avail}",
                })
                volume = avail
        # 限价：买入加缓冲、卖出减缓冲（防开盘跳空废单），取整到分（合法 tick，
        # 三位小数限价会被柜台直接拒单）
        if side == "buy":
            limit_price = round(ref_price * (1 + price_buffer) + 0.005, 2)
        else:
            limit_price = round(ref_price * (1 - price_buffer) - 0.005, 2) if ref_price > 0 else 0.0
        if limit_price <= 0:
            limit_price = 0.0  # 0 → 通道侧市价单

        rules = etf_rules if code in etf_set else base_rules
        rm = risk_manager if code not in etf_set else RiskManager(etf_rules)

        entry = {"code": code, "side": side, "volume": volume,
                 "price": limit_price, "status": "SKIPPED", "reason": ""}
        # 事前风控（组合视图动态更新：卖出回笼资金计入可买额度）
        try:
            pv = portfolio_view()
        except Exception as e:  # noqa: BLE001
            entry.update(status="REJECTED", reason=f"账户查询失败: {type(e).__name__}")
            report.append(entry)
            continue
        # 风控校验用原参考价（非缓冲价，防止缓冲导致误拒）
        ok, reason = rm.pre_trade_check(pv, code, side, ref_price or limit_price, volume, ref_price)
        if not ok:
            entry.update(status="REJECTED", reason=reason)
            report.append(entry)
            continue
        ok2, reason2 = rm.check_frequency(_now_date())
        if not ok2:
            entry.update(status="REJECTED", reason=reason2)
            report.append(entry)
            continue
        # 下单（通道实现负责真实委托；DRY_RUN 时仅本地记录）
        try:
            if side == "buy":
                broker.buy(code, limit_price, volume)
            else:
                broker.sell(code, limit_price, volume)
            entry.update(status="SUBMITTED")
        except Exception as e:  # noqa: BLE001
            entry.update(status="REJECTED", reason=f"{type(e).__name__}: {str(e)[:100]}")
        report.append(entry)
    return report
