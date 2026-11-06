"""
回测引擎测试（含无未来函数/涨跌停/T+1 验证）
"""

from __future__ import annotations

import pandas as pd

from backtest.engine import BacktestEngine
from strategy.examples.dual_ma import DualMAStrategy


def _make_bars(prices: list[float], start: str = "2025-01-01") -> pd.DataFrame:
    """构造标准日线：open=high=low=close=price，volume=1000000。"""
    dates = pd.date_range(start, periods=len(prices), freq="B")
    return pd.DataFrame({
        "date": dates,
        "open": prices, "high": prices, "low": prices, "close": prices,
        "volume": [1_000_000] * len(prices),
        "adj_factor": [1.0] * len(prices),
        "is_trading": [1] * len(prices),
    })


def test_engine_runs_dual_ma():
    """双均线策略在趋势行情中能跑通且产生成交。"""
    # 构造一段先跌后涨的行情：短均线上穿长均线 → 买入
    prices = [10.0] * 10 + list(10 + 0.4 * i for i in range(1, 20))
    bars = {"600000": _make_bars(prices)}
    engine = BacktestEngine(strategy=DualMAStrategy(fast=3, slow=10), initial_cash=1_000_000)
    result = engine.run(bars)

    assert len(result.equity) == len(prices)
    assert len(result.trades) > 0, "趋势行情中双均线应产生交易"
    assert result.metrics["total_return"] >= 0


def test_no_lookahead_bias():
    """无未来函数：信号 T 日产生，成交价必须是 T+1 开盘价（而非 T 日收盘价）。"""
    # 行情：前 15 天 10 元横盘，第 16 天跳涨
    prices = [10.0] * 15 + [12.0] * 10
    bars = {"600000": _make_bars(prices)}
    engine = BacktestEngine(strategy=DualMAStrategy(fast=3, slow=10), initial_cash=1_000_000)
    result = engine.run(bars)

    if result.trades:
        first_buy = next(t for t in result.trades if t["side"] == "buy")
        # 双均线在 T 日收盘确认金叉，T+1 开盘成交——成交价应是跳涨后的 12.0
        assert first_buy["price"] == 12.0, (
            f"成交价 {first_buy['price']} 应为 T+1 开盘价 12.0（若为 10.0 则存在未来函数）"
        )


def test_t_plus_1():
    """T+1：当日买入当日不可卖出。"""
    from backtest.broker_sim import PaperBroker
    broker = PaperBroker(initial_cash=1_000_000)
    broker.buy("600000", 10.0, 1000)
    # 当日卖出应失败（available=0）
    assert broker.sell("600000", 10.0, 1000) is None
    # 次日解锁后可卖
    broker.next_day()
    assert broker.sell("600000", 10.0, 1000) is not None


def test_limit_up_blocks_buy():
    """涨停无法买入（一字板）。"""
    from backtest.broker_sim import can_buy_on_open
    bar = {"open": 11.0, "close": 11.0, "prev_close": 10.0, "is_trading": 1}
    assert can_buy_on_open(bar, limit_rate=0.10) is False


def test_suspended_cannot_trade():
    """停牌不可成交。"""
    from backtest.broker_sim import can_buy_on_open
    bar = {"open": 10.0, "close": 10.0, "prev_close": 10.0, "is_trading": 0}
    assert can_buy_on_open(bar, limit_rate=0.10) is False
