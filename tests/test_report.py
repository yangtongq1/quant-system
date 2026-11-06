"""
报告模块测试：图表生成 + Markdown 报告
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from report.charts import plot_drawdown, plot_equity_curves, plot_monthly_returns_heatmap
from report.performance import generate_report, monthly_returns_table


def _equity(n=300, seed=6):
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2024-01-01", periods=n, freq="B")
    rets = rng.normal(0.0006, 0.012, n)
    return pd.Series(100 * np.cumprod(1 + rets), index=dates)


def test_equity_and_drawdown_charts(tmp_path):
    eq = _equity()
    p1 = plot_equity_curves({"策略A": eq}, out_path=tmp_path / "eq.png")
    p2 = plot_drawdown(eq, out_path=tmp_path / "dd.png")
    assert Path(p1).exists() and Path(p1).stat().st_size > 1000
    assert Path(p2).exists() and Path(p2).stat().st_size > 1000


def test_monthly_heatmap(tmp_path):
    eq = _equity()
    p = plot_monthly_returns_heatmap(eq, out_path=tmp_path / "m.png")
    assert Path(p).exists() and Path(p).stat().st_size > 1000


def test_monthly_table():
    eq = _equity()
    t = monthly_returns_table(eq)
    assert not t.empty
    assert "全年" in t.columns
    # 300 个交易日 ≈ 14 个月，应覆盖两个年份
    assert len(t) >= 2


def test_generate_report(tmp_path):
    eq = _equity()
    trades = [
        {"code": "600519", "side": "buy", "price": 1500.0, "volume": 100, "fee": 37.5},
        {"code": "600519", "side": "sell", "price": 1550.0, "volume": 100, "fee": 42.7},
    ]
    p = generate_report(eq, trades=trades, title="单元测试报告",
                        out_path=tmp_path / "r.md")
    text = Path(p).read_text(encoding="utf-8")
    assert "核心指标" in text
    assert "夏普比率" in text
    assert "交易统计" in text
    assert "月度收益" in text
