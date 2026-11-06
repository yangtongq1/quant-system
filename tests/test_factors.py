"""
因子引擎 + 中性化 + 质检测试
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from factors.engine import FactorEngine, list_factors
from factors.neutralize import neutralize, winsorize_mad, zscore
from factors.qa import qa_report


def _make_bars(n_days: int = 60, seed: int = 42):
    """构造 5 只标的合成日线。"""
    rng = np.random.default_rng(seed)
    codes = [f"60000{i}" for i in range(5)]
    dates = pd.date_range("2025-01-01", periods=n_days, freq="B")
    bars = {}
    for code in codes:
        ret = rng.normal(0.001, 0.02, n_days)
        close = 10 * np.cumprod(1 + ret)
        bars[code] = pd.DataFrame({
            "date": dates,
            "open": close * 0.99, "high": close * 1.01, "low": close * 0.98,
            "close": close, "volume": rng.integers(1e6, 5e6, n_days).astype(float),
            "adj_factor": 1.0,
        })
    return codes, dates, bars


def test_factor_registry_and_engine():
    """因子注册表 + 引擎批量计算。"""
    names = list_factors()
    assert "momentum_20d" in names
    assert "volatility_20d" in names

    _, _, bars = _make_bars()
    engine = FactorEngine(bars)
    panel = engine.compute("momentum_20d")
    # 60 天数据，前 20 天 NaN，后 40 天有值
    assert panel.shape[0] == 60
    assert panel.notna().sum().sum() > 0
    # 缓存生效：二次计算返回同一对象
    assert engine.compute("momentum_20d") is panel


def test_neutralize_basic():
    """中性化：去极值 + 标准化 + 行业/市值残差化。"""
    rng = np.random.default_rng(0)
    codes = [f"6000{i:03d}" for i in range(30)]
    factor = pd.Series(rng.normal(0, 1, 30), index=codes)
    industry = pd.Series(["银行"] * 10 + ["白酒"] * 10 + ["医药"] * 10, index=codes)
    mv = pd.Series(rng.lognormal(22, 1, 30), index=codes)

    out = neutralize(factor.to_frame("f"), industry=industry, mv=mv)
    assert len(out) == 30
    # 标准化后均值≈0、标准差≈1
    assert abs(out["f"].mean()) < 1e-9
    assert abs(out["f"].std() - 1) < 0.1


def test_winsorize_mad():
    """MAD 去极值：极端值被截断。"""
    s = pd.Series([1.0, 1.1, 0.9, 1.05, 0.95, 100.0])
    w = winsorize_mad(s)
    assert w.max() < 100.0
    assert w.min() >= 0.9


def test_qa_report_synthetic():
    """质检报告：构造「真因子 + 噪声」数据，IC 应显著为正。"""
    rng = np.random.default_rng(7)
    n_dates, n_codes = 40, 50
    dates = pd.date_range("2025-01-01", periods=n_dates, freq="B")
    codes = [f"0000{i:02d}" for i in range(n_codes)]

    # 因子值
    factor_values = rng.normal(0, 1, (n_dates, n_codes))
    factor_panel = pd.DataFrame(factor_values, index=dates, columns=codes)

    # 下期收益 = 0.3×因子 + 噪声（alpha=0.3，应检出正 IC）
    noise = rng.normal(0, 0.02, (n_dates, n_codes))
    ret_values = 0.3 * factor_values + noise
    fwd = pd.DataFrame(ret_values, index=dates, columns=codes)

    report = qa_report(factor_panel, fwd)
    assert report["ic_mean"] > 0.5, f"IC={report['ic_mean']} 应显著为正"
    assert report["coverage"] == 1.0
    # 分层单调性应接近 1
    assert report["monotonicity"] > 0.8


def test_qa_report_pure_noise():
    """纯噪声因子 IC 应接近 0。"""
    rng = np.random.default_rng(11)
    n_dates, n_codes = 40, 50
    dates = pd.date_range("2025-01-01", periods=n_dates, freq="B")
    codes = [f"0000{i:02d}" for i in range(n_codes)]
    factor_panel = pd.DataFrame(rng.normal(0, 1, (n_dates, n_codes)), index=dates, columns=codes)
    fwd = pd.DataFrame(rng.normal(0, 0.02, (n_dates, n_codes)), index=dates, columns=codes)

    report = qa_report(factor_panel, fwd)
    assert abs(report["ic_mean"]) < 0.2
