"""
因子中性化（多因子选股标配，不可省略）

流程：
1. 截面去极值（MAD 法）+ z-score 标准化
2. 行业中性：因子值对行业哑变量回归取残差
3. 市值中性：残差对对数市值回归取残差

线性回归用 numpy 最小二乘，不引入 statsmodels/sklearn。
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def winsorize_mad(series: pd.Series, n_mad: float = 3.0) -> pd.Series:
    """MAD 法去极值。中位数 ± n×MAD×1.4826（正态一致性尺度）。"""
    s = series.astype(float)
    med = s.median()
    mad = (s - med).abs().median()
    if mad == 0 or np.isnan(mad):
        return s
    bound = n_mad * mad * 1.4826
    return s.clip(med - bound, med + bound)


def zscore(series: pd.Series) -> pd.Series:
    """z-score 标准化（截面）。"""
    s = series.astype(float)
    std = s.std()
    if std == 0 or np.isnan(std):
        return s * 0.0
    return (s - s.mean()) / std


def neutralize(
    factor_panel: pd.DataFrame,
    industry: pd.Series | None = None,
    mv: pd.Series | None = None,
) -> pd.DataFrame:
    """截面中性化：去极值 + 标准化 + 行业/市值中性。

    参数
    ----
    factor_panel : 单期截面因子值（index=code, columns=[factor_names]）
    industry : index=code, value=行业（可选）
    mv : index=code, value=市值（可选，取对数回归）
    """
    df = factor_panel.copy().astype(float)

    # 逐列：去极值 + 标准化
    for col in df.columns:
        df[col] = winsorize_mad(df[col])
        df[col] = zscore(df[col])

    # 构造回归 X：行业哑变量 + log 市值
    xs: list[pd.DataFrame] = []
    if industry is not None:
        ind = industry.reindex(df.index)
        if ind.notna().sum() > 0:
            dummies = pd.get_dummies(ind.astype(str), drop_first=True).astype(float)
            if dummies.shape[1] > 0:
                xs.append(dummies)
    if mv is not None:
        log_mv = pd.Series(
            np.log(mv.reindex(df.index).clip(lower=1.0).astype(float)),
            index=df.index, name="log_mv",
        )
        if log_mv.notna().sum() > 2:
            xs.append(log_mv.to_frame())

    if not xs:
        return df  # 无中性化变量，仅标准化

    X = pd.concat(xs, axis=1)
    valid = X.notna().all(axis=1)
    X_valid = X[valid]
    if len(X_valid) < X.shape[1] + 2:
        return df  # 样本不足，跳过回归

    # 最小二乘：factor = X @ beta + resid，取残差
    X_mat = np.column_stack([np.ones(len(X_valid)), X_valid.values])
    for col in df.columns:
        y = df.loc[X_valid.index, col].values
        beta, *_ = np.linalg.lstsq(X_mat, y, rcond=None)
        resid = y - X_mat @ beta
        df.loc[X_valid.index, col] = resid
    # 重新标准化残差（所有列）
    for col in df.columns:
        df[col] = zscore(df[col])
    return df


def neutralize_panel(
    panels: dict[str, pd.DataFrame],
    industry=None,
    mv=None,
) -> dict[str, pd.DataFrame]:
    """逐日期截面中性化（panels: {factor: DataFrame(date×code)}）。

    industry / mv 可为 Series（静态截面）或 DataFrame(date×code)（时变）。
    返回 {factor_name: DataFrame(date×code)}，列对齐到各期公共标的集。
    """
    dates = None
    for panel in panels.values():
        dates = panel.index if dates is None else dates.intersection(panel.index)

    out: dict[str, pd.DataFrame] = {}
    for d in dates:
        cross: dict[str, pd.Series] = {}
        for name, panel in panels.items():
            s = panel.loc[d].dropna()
            if len(s) > 0:
                cross[name] = s
        if len(cross) < 2:
            continue
        cross_df = pd.DataFrame(cross)

        ind = industry
        if industry is not None and isinstance(industry, pd.DataFrame) and d in industry.index:
            ind = industry.loc[d]
        m = mv
        if mv is not None and isinstance(mv, pd.DataFrame) and d in mv.index:
            m = mv.loc[d]

        neutral = neutralize(cross_df, industry=ind, mv=m)
        for name in neutral.columns:
            if name not in out:
                out[name] = pd.DataFrame(index=dates)
            out[name].loc[d, neutral.index] = neutral[name].values
    return out
