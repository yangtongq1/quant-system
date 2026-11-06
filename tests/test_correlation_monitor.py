"""相关性监控模块测试。"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from risk.correlation_monitor import CorrelationMonitor


def _make_prices(stock_ret, gold_ret, nasdaq_ret):
    n = len(stock_ret)
    dates = pd.date_range("2024-01-01", periods=n)
    return pd.DataFrame({
        "stock": 100 * np.exp(np.cumsum(stock_ret)),
        "gold": 100 * np.exp(np.cumsum(gold_ret)),
        "nasdaq": 100 * np.exp(np.cumsum(nasdaq_ret)),
    }, index=dates)


def test_monitor_columns():
    np.random.seed(0)
    n = 120
    prices = _make_prices(
        np.random.normal(0, 0.01, n),
        np.random.normal(0, 0.01, n),
        np.random.normal(0, 0.01, n),
    )
    m = CorrelationMonitor(window=30)
    corr = m.monitor(prices)
    assert set(corr.columns) == {"gold_stock_corr", "nasdaq_stock_corr"}
    assert corr["gold_stock_corr"].notna().sum() > 0  # 窗口后应有有效值


def test_high_corr_triggers_alert():
    """纳指与股票高度正相关 → 应触发告警。"""
    np.random.seed(1)
    n = 120
    stock_ret = np.random.normal(0, 0.01, n)
    nasdaq_ret = stock_ret * 0.9 + np.random.normal(0, 0.002, n)  # 高度正相关
    gold_ret = np.random.normal(0, 0.01, n)                       # 独立
    prices = _make_prices(stock_ret, gold_ret, nasdaq_ret)

    m = CorrelationMonitor(window=60)
    result = m.check_latest(prices)
    assert result["status"] == "alert"
    assert result["nasdaq_stock_corr"] > 0.7
    assert any("纳指" in a for a in result["alerts"])


def test_low_corr_ok():
    """三者独立 → 应不告警。"""
    np.random.seed(2)
    n = 120
    prices = _make_prices(
        np.random.normal(0, 0.01, n),
        np.random.normal(0, 0.01, n),
        np.random.normal(0, 0.01, n),
    )
    m = CorrelationMonitor(window=60)
    result = m.check_latest(prices)
    assert result["status"] == "ok"
    assert result["alerts"] == []
