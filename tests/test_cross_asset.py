"""
跨资产策略测试：λ 并轨 / 风险平价 / 裁剪 / 选股 / 再平衡
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from strategy.cross_asset import CrossAssetStrategy


def _make_bars(prices: list[float], start="2025-01-01") -> pd.DataFrame:
    dates = pd.date_range(start, periods=len(prices), freq="B")
    return pd.DataFrame({
        "date": dates, "open": prices, "high": prices, "low": prices, "close": prices,
        "volume": [1e6] * len(prices), "adj_factor": [1.0] * len(prices), "is_trading": [1] * len(prices),
    })


def _to_acc(series: pd.Series):
    """pd.Series → 策略内部累积器。"""
    acc = CrossAssetStrategy._SeriesAcc(series.index[0], float(series.iloc[0]))
    for d, v in zip(series.index[1:], series.values[1:]):
        acc.append(d, float(v))
    return acc


def test_lambda_blend():
    """λ 并轨：λ=0 时最终权重=基准；λ=1 时=动态。"""
    n = 200
    rng = np.random.default_rng(1)
    stock = 10 * np.cumprod(1 + rng.normal(0.001, 0.015, n))
    gold = 5 * np.cumprod(1 + rng.normal(0.0005, 0.008, n))   # 低波动
    nasdaq = 2 * np.cumprod(1 + rng.normal(0.0012, 0.02, n))   # 高波动
    dates = pd.date_range("2025-01-01", periods=n, freq="B")

    def make_strategy(lam):
        s = CrossAssetStrategy(lam=lam, top_n=10, lookback=60)
        s._stock_close = {
            code: _to_acc(pd.Series(stock * (1 + 0.01 * i), index=dates))
            for i, code in enumerate(["600000", "600001"])
        }
        s._gold_close = _to_acc(pd.Series(gold, index=dates))
        s._nasdaq_close = _to_acc(pd.Series(nasdaq, index=dates))
        return s

    s0 = make_strategy(0.0)
    w0 = s0.target_weights()
    assert abs(w0["stock"] - 0.6) < 1e-9
    assert abs(w0["gold"] - 0.2) < 1e-9
    assert abs(w0["nasdaq"] - 0.2) < 1e-9

    s1 = make_strategy(1.0)
    w1 = s1.target_weights()
    assert abs(w1["stock"] - s1.dynamic_weights()["stock"]) < 1e-9

    # λ=0.5 各权重应介于基准与动态之间
    s5 = make_strategy(0.5)
    w5 = s5.target_weights()
    dyn = s5.dynamic_weights()
    for k in ("stock", "gold", "nasdaq"):
        lo, hi = sorted((0.2 if k != "stock" else 0.6, dyn[k]))
        assert lo - 1e-9 <= w5[k] <= hi + 1e-9


def test_dynamic_weights_low_vol_gets_more():
    """风险平价：低波动资产（黄金）权重应高于高波动（纳指）。"""
    n = 200
    rng = np.random.default_rng(2)
    s = CrossAssetStrategy(lam=1.0, top_n=10, lookback=60)
    dates = pd.date_range("2025-01-01", periods=n, freq="B")
    s._stock_close = {"600000": _to_acc(pd.Series(10 + rng.normal(0, 0.01, n).cumsum(), index=dates))}
    s._gold_close = _to_acc(pd.Series(5 + rng.normal(0, 0.002, n).cumsum(), index=dates))      # 极低波动
    s._nasdaq_close = _to_acc(pd.Series(2 + rng.normal(0, 0.05, n).cumsum(), index=dates))     # 极高波动
    w = s.dynamic_weights()
    assert w["gold"] > w["nasdaq"], "低波动资产应获得更高权重"


def test_clip_bounds():
    """裁剪：单资产权重在 [10%, 70%] 内。"""
    s = CrossAssetStrategy()
    w = s._clip_weights({"stock": 0.95, "gold": 0.03, "nasdaq": 0.02})
    assert all(0.10 - 1e-6 <= v <= 0.70 + 1e-6 for v in w.values())
    assert abs(sum(w.values()) - 1.0) < 1e-6


def test_select_stocks_top_n():
    """选股：按综合分选出 top N，数量正确。"""
    n = 200
    rng = np.random.default_rng(3)
    dates = pd.date_range("2025-01-01", periods=n, freq="B")
    s = CrossAssetStrategy(top_n=3)
    # 5 只股票，动量差异明显
    for i in range(5):
        drift = 0.001 * i  # 编号越大动量越强
        px = 10 * np.cumprod(1 + rng.normal(drift, 0.01, n))
        s._stock_close[f"60000{i}"] = _to_acc(pd.Series(px, index=dates))

    selected = s.select_stocks()
    assert len(selected) == 3
    # 动量最强的 600004 应在选中集合
    assert "600004" in selected


def test_month_end_rebalance_trades():
    """月末再平衡能触发调仓订单。"""
    from backtest.engine import BacktestEngine

    n = 130
    rng = np.random.default_rng(4)
    bars = {}
    bars["518880"] = _make_bars((5 * np.cumprod(1 + rng.normal(0.0005, 0.008, n))).tolist())
    bars["513100"] = _make_bars((2 * np.cumprod(1 + rng.normal(0.001, 0.02, n))).tolist())
    codes = ["600000", "600001", "600002"]
    for i, c in enumerate(codes):
        px = 10 * np.cumprod(1 + rng.normal(0.001, 0.015, n))
        bars[c] = _make_bars(px.tolist())

    strategy = CrossAssetStrategy(lam=0.5, top_n=2, lookback=60)
    engine = BacktestEngine(strategy=strategy, initial_cash=1_000_000)
    result = engine.run(bars)

    # 130 天 ≈ 6 个月，至少触发一次月末再平衡 → 应有成交
    assert len(result.trades) > 0, "130 天跨 6 个月，月末再平衡应产生交易"
    # 成交应含 ETF（黄金/纳指）
    traded = {t["code"] for t in result.trades}
    assert "518880" in traded or "513100" in traded, "再平衡应交易 ETF"
    assert result.metrics["max_drawdown"] <= 0.0
