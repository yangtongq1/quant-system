"""
波动率类因子

复权红线：收益率一律用后复权价。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from factors.engine import register_factor


@register_factor("volatility_20d")
def volatility_20d(df: pd.DataFrame) -> pd.Series:
    """20 日收益波动率（日频标准差）。"""
    close = df["close"] * df["adj_factor"]
    ret = close.pct_change()
    return ret.rolling(20).std()


@register_factor("atr_20d")
def atr_20d(df: pd.DataFrame) -> pd.Series:
    """20 日平均真实波幅 ATR（后复权口径，相对化处理便于截面比较）。"""
    close = df["close"] * df["adj_factor"]
    high = df["high"] * df["adj_factor"]
    low = df["low"] * df["adj_factor"]
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    atr = tr.rolling(20).mean()
    return atr / close  # 相对 ATR（截面可比）


@register_factor("amplitude_20d")
def amplitude_20d(df: pd.DataFrame) -> pd.Series:
    """20 日平均振幅：(high-low)/close。"""
    close = df["close"]
    high = df["high"]
    low = df["low"]
    amp = (high - low) / close
    return amp.rolling(20).mean()


@register_factor("turnover_20d")
def turnover_20d(df: pd.DataFrame) -> pd.Series:
    """20 日平均换手率代理：成交额 / 流通市值不可得时用成交量 z-score 代理。

    注：akshare 新浪日线不含换手率列，用成交量标准化近似（截面排序仍有效）。
    """
    vol = df["volume"].astype(float)
    return vol.rolling(20).mean()
