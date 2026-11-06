"""
Walk-Forward 优化器测试
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from backtest.optimizer import WalkForwardOptimizer
from strategy.examples.dual_ma import DualMAStrategy


def _make_bars(n=150, seed=5):
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2025-01-01", periods=n, freq="B")
    # 趋势 + 噪声行情（均线策略有信号空间）
    trend = np.linspace(0, 2.0, n)
    close = 10 * (1 + trend) + rng.normal(0, 0.25, n)
    return {"600000": pd.DataFrame({
        "date": dates, "open": close, "high": close * 1.01, "low": close * 0.99,
        "close": close, "volume": [1e6] * n, "adj_factor": [1.0] * n, "is_trading": [1] * n,
    })}


def test_walk_forward_splits():
    """Walk-Forward：训练/测试两段分离，测试段成绩独立输出。"""
    bars = _make_bars()
    opt = WalkForwardOptimizer(
        make_strategy=lambda **p: DualMAStrategy(**p),
        param_grid={"fast": [3, 5], "slow": [10, 20]},
        metric="sharpe",
    )
    report = opt.optimize(bars, train_ratio=0.7)

    assert "best_params" in report
    assert report["best_params"]["fast"] < report["best_params"]["slow"]
    # 训练/测试成绩都存在（测试成绩独立计算）
    assert "train_score" in report and "test_score" in report
    # 全部 4 组参数都有训练成绩
    assert len(report["all_train_scores"]) == 4


def test_neighborhood_stability_present():
    """邻域稳健性输出存在。"""
    bars = _make_bars()
    opt = WalkForwardOptimizer(
        make_strategy=lambda **p: DualMAStrategy(**p),
        param_grid={"fast": [3, 5], "slow": [10, 20]},
    )
    report = opt.optimize(bars)
    assert "stability" in report
    assert report["stability"]["n_neighbors"] > 0
