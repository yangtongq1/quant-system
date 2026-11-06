"""
价值类因子（PE/PB/股息率）

数据来源：估值表（由调用方提供，如 akshare 实时估值快照或 SuperMind 估值接口）。
估值数据滞后性：使用时以「报告期」对齐，财务数据可用日期 = 报告期 + 滞后天数。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from factors.engine import register_factor


def build_value_factors(valuation: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """由估值表构建价值因子面板。

    参数
    ----
    valuation : 列 [code, date, pe, pb, dividend_yield]，
                date 为估值快照日期（滞后性由调用方保证）
    返回 {factor_name: panel(date×code)}
    """
    if valuation is None or valuation.empty:
        return {}
    val = valuation.copy()
    val["date"] = pd.to_datetime(val["date"])
    piv = val.pivot_table(index="date", columns="code", values=["pe", "pb", "dividend_yield"])
    out = {}
    for metric in ("pe", "pb", "dividend_yield"):
        if (metric, ) in piv.columns.get_level_values(0):
            panel = piv[metric]
            # EP/BP：估值因子统一用倒数（低估值为正贡献），pe/pb<=0 剔除为 NaN
            if metric in ("pe", "pb"):
                panel = panel.where(panel > 0)
                panel = 1.0 / panel
            out[f"{metric}_factor"] = panel.sort_index()
    return out


@register_factor("ep_ratio")
def ep_ratio(df: pd.DataFrame) -> pd.Series | None:
    """EP 比率（1/PE）。单标的日线无估值列时返回 None（价值因子走 build_value_factors）。"""
    if "pe" not in df.columns:
        return None
    pe = pd.to_numeric(df["pe"], errors="coerce")
    pe = pe.where(pe > 0)
    return 1.0 / pe
