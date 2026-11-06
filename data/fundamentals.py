"""
基本面数据加载器（point-in-time）

职责：从 SQLite fundamentals 表读取财报数据，按「公告日对齐」构造截面面板。
红线：point-in-time——某交易日的截面只能用「已公告」的最新报告期数据，
杜绝用未来才披露的财报（财报公告日通常在报告期后 1-4 个月）。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "quant.db"


def load_fundamentals(db: str | Path | None = None) -> pd.DataFrame:
    """读取 fundamentals 长表。返回列：
    code / period / report_date / roe / gross_margin / revenue_yoy / profit_yoy / eps / bvps / industry
    """
    db_path = Path(db) if db else DB
    if not db_path.exists():
        return pd.DataFrame()
    conn = sqlite3.connect(str(db_path))
    try:
        df = pd.read_sql("SELECT * FROM fundamentals", conn)
    finally:
        conn.close()
    if df.empty:
        return df
    df["report_date"] = pd.to_datetime(df["report_date"], errors="coerce")
    df["period"] = pd.to_datetime(df["period"], errors="coerce")
    return df


def point_in_time_panel(
    fund: pd.DataFrame,
    metric: str,
    dates: pd.DatetimeIndex,
    extra_lag_days: int = 1,
) -> pd.DataFrame:
    """构造 point-in-time 截面面板。

    参数
    ----
    fund : fundamentals 长表（load_fundamentals 输出）
    metric : 指标列（roe / gross_margin / revenue_yoy / profit_yoy / eps / bvps）
    dates : 目标交易日轴
    extra_lag_days : 公告日之后再额外滞后的天数（默认 1，防公告当日数据未入库）

    返回 DataFrame(index=dates, columns=code)，值 = 每个交易日已公告的最新报告期指标。
    """
    if fund.empty or metric not in fund.columns:
        return pd.DataFrame(index=dates)

    df = fund.dropna(subset=["report_date", "code"]).copy()
    # 公告可用日 = 公告日 + 额外滞后
    df["available_date"] = df["report_date"] + pd.Timedelta(days=extra_lag_days)

    out = pd.DataFrame(np.nan, index=dates, columns=sorted(df["code"].unique()))
    for code, g in df.groupby("code"):
        g = g.dropna(subset=[metric])
        if g.empty:
            continue
        g = g.sort_values("available_date").drop_duplicates(subset="available_date", keep="last")
        s = pd.Series(g[metric].values, index=g["available_date"].values).sort_index()
        # as-of 对齐：每个交易日取已公告的最新值
        out[code] = s.reindex(dates, method="ffill").values
    return out


def industry_map(fund: pd.DataFrame) -> pd.Series:
    """最新行业映射（code -> industry）。"""
    if fund.empty:
        return pd.Series(dtype=str)
    latest = fund.sort_values("period").drop_duplicates(subset="code", keep="last")
    return latest.set_index("code")["industry"]
