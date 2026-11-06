"""绩效计算模块测试：用已知序列验证指标精确值。"""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backtest.metrics import compute_metrics, max_drawdown


def test_total_return():
    eq = pd.Series([100.0, 110.0, 121.0])
    m = compute_metrics(eq)
    assert abs(m["total_return"] - 0.21) < 1e-9


def test_max_drawdown():
    eq = pd.Series([100.0, 120.0, 90.0, 100.0])
    assert abs(max_drawdown(eq) - (-0.25)) < 1e-9


def test_flat_series():
    eq = pd.Series([100.0, 100.0, 100.0])
    m = compute_metrics(eq)
    assert m["total_return"] == 0.0
    assert m["volatility"] == 0.0
    assert m["max_drawdown"] == 0.0


def test_sharpe_positive_for_uptrend():
    eq = pd.Series([100.0, 101.0, 102.0, 103.0, 104.0])
    m = compute_metrics(eq)
    assert m["sharpe"] > 0
    assert m["win_rate"] == 1.0


def test_win_rate():
    # 日收益：+10%, -5% → 胜率 0.5
    eq = pd.Series([100.0, 110.0, 104.5])
    m = compute_metrics(eq)
    assert abs(m["win_rate"] - 0.5) < 1e-9


def test_calmar():
    # 年化 > 0 且存在回撤，卡玛应为正
    eq = pd.Series([100.0, 110.0, 99.0, 120.0])
    m = compute_metrics(eq)
    assert m["max_drawdown"] < 0
    assert m["calmar"] > 0
