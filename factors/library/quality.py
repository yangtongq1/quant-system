"""
质量类因子（ROE/毛利率/营收增速）

数据来源：基本面表（fetch_fundamentals 采集，按报告期存储）。
滞后性红线：财报数据在报告期后才可用（年报 4 月底、季报披露后），
计算截面因子时只用「已披露」的最新报告期数据（point-in-time 对齐）。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from factors.engine import register_factor


def build_quality_factors(fundamentals: pd.DataFrame, lag_days: int = 30) -> dict[str, pd.DataFrame]:
    """由基本面表构建质量因子面板（point-in-time）。

    参数
    ----
    fundamentals : 长表 [code, period, roe, gross_margin, revenue_yoy, ...]
                   period 为报告期（如 '2025-12-31'）
    lag_days : 披露滞后天数（报告期 + lag 天后才可用，防未来函数）
    返回 {factor_name: panel(date×code)}，每个日期使用「已披露的最新报告期」数据
    """
    if fundamentals is None or fundamentals.empty:
        return {}
    fund = fundamentals.copy()
    fund["period"] = pd.to_datetime(fund["period"], errors="coerce")
    fund = fund.dropna(subset=["period"])
    # 可用日期 = 报告期 + 滞后天数
    fund["available_date"] = fund["period"] + pd.Timedelta(days=lag_days)

    metrics = [c for c in ("roe", "gross_margin", "revenue_yoy", "profit_yoy",
                           "net_margin", "debt_ratio") if c in fund.columns]
    if not metrics:
        return {}

    # 全日期轴：可用日期 → 期末
    all_dates = pd.date_range(fund["available_date"].min(), fund["available_date"].max(), freq="B")
    out: dict[str, pd.DataFrame] = {m: pd.DataFrame(index=all_dates) for m in metrics}

    fund = fund.sort_values(["code", "period"])
    for code, g in fund.groupby("code"):
        g = g.drop_duplicates(subset="period", keep="last")
        for m in metrics:
            s = pd.Series(g[m].values, index=g["available_date"].values)
            s = s[~s.index.duplicated(keep="last")].sort_index()
            # as-of 对齐：每个交易日取「已披露的最新值」
            out[m][code] = s.reindex(all_dates, method="ffill").values
    return out
