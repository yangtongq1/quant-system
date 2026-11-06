"""
动量类因子

每个因子函数：输入单标的日线 DataFrame（date/close/volume/adj_factor...），
输出 pd.Series（索引=date，值=因子值）。

复权红线：收益率计算一律用后复权价（close × adj_factor），杜绝除权跳空污染动量。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from factors.engine import register_factor


@register_factor("momentum_20d")
def momentum_20d(df: pd.DataFrame) -> pd.Series:
    """20 日动量：过去 20 日累计收益率（后复权口径）。"""
    close = df["close"] * df["adj_factor"]
    return close.pct_change(20)


@register_factor("momentum_60d")
def momentum_60d(df: pd.DataFrame) -> pd.Series:
    """60 日动量。"""
    close = df["close"] * df["adj_factor"]
    return close.pct_change(60)


@register_factor("momentum_120d")
def momentum_120d(df: pd.DataFrame) -> pd.Series:
    """120 日动量。"""
    close = df["close"] * df["adj_factor"]
    return close.pct_change(120)


@register_factor("ma_bias_20d")
def ma_bias_20d(df: pd.DataFrame) -> pd.Series:
    """20 日均线偏离：(价格 - MA20) / MA20（后复权口径）。"""
    close = df["close"] * df["adj_factor"]
    ma = close.rolling(20).mean()
    return (close - ma) / ma


@register_factor("reversal_5d")
def reversal_5d(df: pd.DataFrame) -> pd.Series:
    """5 日反转：过去 5 日收益率取负（短期跌多者未来反弹倾向）。"""
    close = df["close"] * df["adj_factor"]
    return -close.pct_change(5)
