"""
因子质检（M3 必做）

入库前每个因子输出质检报告：
1. IC / ICIR：因子值与下期收益的截面相关系数及稳定性
2. 分层收益：按因子值分 5/10 组，看组间收益单调性
3. 覆盖率：有效值占样本比例
4. 去相关：与存量因子相关性矩阵，超 0.6 告警
5. 稳定性：分年度 IC 是否一致（防某一年单点贡献）
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def information_coefficient(
    factor_panel: pd.DataFrame,
    forward_returns: pd.DataFrame,
) -> pd.Series:
    """逐期 IC：每期截面 Spearman 秩相关（因子值 vs 下期收益）。

    参数
    ----
    factor_panel : DataFrame(date×code)
    forward_returns : DataFrame(date×code)，与 factor_panel 同形状，
                     行 d 的值 = d+1 期收益（即未来一期收益，由调用方构造）
    """
    common_dates = factor_panel.index.intersection(forward_returns.index)
    ics = []
    ic_dates = []
    for d in common_dates:
        f = factor_panel.loc[d]
        r = forward_returns.loc[d]
        df = pd.concat([f, r], axis=1, keys=["factor", "ret"]).dropna()
        if len(df) < 5:
            continue
        if df["factor"].std() == 0 or df["ret"].std() == 0:
            continue
        ic = df["factor"].corr(df["ret"], method="spearman")
        if pd.notna(ic):
            ics.append(ic)
            ic_dates.append(d)
    return pd.Series(ics, index=ic_dates)


def layered_returns(
    factor_panel: pd.DataFrame,
    forward_returns: pd.DataFrame,
    n_groups: int = 5,
) -> pd.DataFrame:
    """分层收益：每期按因子值分 n 组，输出各组平均下期收益（时序平均）。

    返回 DataFrame(index=组号[1..n], columns=[mean_ret, monoticity_helper])
    """
    common_dates = factor_panel.index.intersection(forward_returns.index)
    group_rets: list[np.ndarray] = [[] for _ in range(n_groups)]
    for d in common_dates:
        f = factor_panel.loc[d]
        r = forward_returns.loc[d]
        df = pd.concat([f, r], axis=1, keys=["factor", "ret"]).dropna()
        if len(df) < n_groups:
            continue
        try:
            groups = pd.qcut(df["factor"].rank(method="first"), n_groups, labels=False)
        except ValueError:
            continue
        for g in range(n_groups):
            mask = groups == g
            if mask.any():
                group_rets[g].append(df.loc[mask, "ret"].mean())

    rows = []
    for g in range(n_groups):
        vals = group_rets[g]
        rows.append({
            "group": g + 1,
            "mean_ret": float(np.mean(vals)) if vals else np.nan,
            "n_days": len(vals),
        })
    return pd.DataFrame(rows).set_index("group")


def coverage(factor_panel: pd.DataFrame) -> float:
    """覆盖率：非 NaN 值占比。"""
    return float(factor_panel.notna().sum().sum() / factor_panel.size)


def correlation_with(factor_panel: pd.DataFrame, other: pd.DataFrame) -> pd.Series:
    """与存量因子的截面相关性（逐期相关系数的时序均值）。"""
    common_dates = factor_panel.index.intersection(other.index)
    common_codes = factor_panel.columns.intersection(other.columns)
    if not len(common_dates) or not len(common_codes):
        return pd.Series(dtype=float)
    corrs = []
    for d in common_dates:
        f = factor_panel.loc[d, common_codes]
        o = other.loc[d, common_codes]
        df = pd.concat([f, o], axis=1, keys=["a", "b"]).dropna()
        if len(df) < 5 or df["a"].std() == 0 or df["b"].std() == 0:
            continue
        c = df["a"].corr(df["b"])
        if pd.notna(c):
            corrs.append(c)
    return pd.Series(corrs).mean() if corrs else pd.Series(dtype=float)


def yearly_ic(
    factor_panel: pd.DataFrame,
    forward_returns: pd.DataFrame,
) -> pd.Series:
    """分年度 IC（稳定性检验）。返回 index=年份, value=年均 IC。"""
    ic_series = information_coefficient(factor_panel, forward_returns)
    if ic_series.empty:
        return pd.Series(dtype=float)
    idx = pd.DatetimeIndex(ic_series.index)
    years = idx.year
    return ic_series.groupby(years).mean()


def qa_report(
    factor_panel: pd.DataFrame,
    forward_returns: pd.DataFrame,
    existing: dict[str, pd.DataFrame] | None = None,
    n_groups: int = 5,
) -> dict:
    """完整质检报告。

    返回 dict：
    {ic_mean, icir, ic_win_rate, coverage, layering, yearly_ic, corr_alerts}
    """
    ic = information_coefficient(factor_panel, forward_returns)
    ic_mean = float(ic.mean()) if len(ic) else np.nan
    ic_std = float(ic.std()) if len(ic) > 1 else np.nan
    icir = float(ic.mean() / ic.std()) if len(ic) > 1 and ic.std() > 0 else np.nan

    layer = layered_returns(factor_panel, forward_returns, n_groups)
    # 单调性：组间收益与组号的秩相关（1=完全单调递增）
    mono = np.nan
    if len(layer) == n_groups and layer["mean_ret"].notna().all():
        mono = float(layer["mean_ret"].corr(layer.index.to_series(), method="spearman"))

    cov = coverage(factor_panel)

    corr_alerts = []
    if existing:
        for name, panel in existing.items():
            c = correlation_with(factor_panel, panel)
            if pd.notna(c) and abs(c) > 0.6:
                corr_alerts.append({"factor": name, "corr": round(float(c), 3)})

    yic = yearly_ic(factor_panel, forward_returns)
    # 分年 IC 方向一致性：正负号一致年占比
    sign_consistency = float((np.sign(yic) == np.sign(ic_mean)).mean()) if len(yic) else np.nan

    return {
        "ic_mean": ic_mean,
        "icir": icir,
        "ic_win_rate": float((ic > 0).mean()) if len(ic) else np.nan,
        "coverage": cov,
        "layering": layer,
        "monotonicity": mono,
        "yearly_ic": yic,
        "sign_consistency": sign_consistency,
        "corr_alerts": corr_alerts,
    }
