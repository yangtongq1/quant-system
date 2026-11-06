"""
数据清洗模块（难点模块之一）

职责：把原始日线数据清洗为标准格式，处理停牌 / 复权 / 异常值。

红线（智谱接续开发务必遵守）：
1. 统一存「不复权价 + 复权因子 adj_factor」，回测时按需复权，口径显式传入，不做隐式默认。
2. 停牌日保留记录、标记 is_trading=0，不得用前值填充制造假行情。
3. 幸存者偏差在采集层处理（采集须含退市股），本模块不剔除任何标的。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

# 日线数据必须包含的列
REQUIRED_COLS = {"date", "open", "high", "low", "close", "volume"}


def clean_daily_bars(
    df: pd.DataFrame,
    adj_factor: pd.Series | None = None,
    limit_pct: float = 0.21,
    strict: bool = True,
) -> pd.DataFrame:
    """清洗单标的日线数据，输出标准格式。

    参数
    ----
    df : 原始数据，须含列 date/open/high/low/close/volume
    adj_factor : 复权因子（索引须能对齐到 date），缺省置 1.0
    limit_pct : 单日涨跌幅告警阈值（默认 21%，覆盖主板/创业板/ST）
    strict : True 时遇致命异常（缺列、价格<=0）抛异常；False 仅打告警日志

    返回
    ----
    标准 DataFrame，列：
        date / open / high / low / close / volume / adj_factor /
        prev_close / is_trading
    """
    # 1. 列校验
    missing = REQUIRED_COLS - set(df.columns)
    if missing:
        raise ValueError(f"缺少必要列: {sorted(missing)}")

    out = df.copy()
    out["date"] = pd.to_datetime(out["date"])

    # 2. 排序 + 去重（同一日期保留最后一条）
    out = out.sort_values("date").drop_duplicates(subset="date", keep="last").reset_index(drop=True)

    # 3. 复权因子对齐（优先 adj_factor 参数，其次 df 自带列，否则置 1.0）
    if adj_factor is not None:
        af = pd.Series(adj_factor).astype(float)
        # 按 date 对齐，缺失置 1.0
        out["adj_factor"] = af.reindex(out["date"]).fillna(1.0).values
    elif "adj_factor" in out.columns:
        out["adj_factor"] = pd.to_numeric(out["adj_factor"], errors="coerce").fillna(1.0).values
    else:
        out["adj_factor"] = 1.0

    # 4. 停牌标记：无成交（volume 缺失或 <=0）视为停牌
    out["volume"] = pd.to_numeric(out["volume"], errors="coerce").fillna(0.0)
    out["is_trading"] = (out["volume"] > 0).astype(int)

    # 5. 致命异常校验：价格 <= 0
    for col in ("open", "high", "low", "close"):
        bad = pd.to_numeric(out[col], errors="coerce") <= 0
        n_bad = int(bad.sum())
        if n_bad > 0:
            if strict:
                raise ValueError(f"列 {col} 存在 {n_bad} 条价格<=0 的异常记录")
            print(f"[cleaner] 告警: 列 {col} 存在 {n_bad} 条价格<=0 的异常记录")

    # 6. 昨收价（用于后续涨跌停判断，不复权价口径）
    out["prev_close"] = out["close"].shift(1)

    # 7. 异常波动告警（基于前复权近似，避免除权跳空误报时可用 limit_pct 放宽）
    ret = out["close"].pct_change().abs()
    spikes = ret > limit_pct
    if int(spikes.sum()) > 0:
        print(f"[cleaner] 告警: 存在 {int(spikes.sum())} 条单日涨跌幅超 {limit_pct:.0%} 的记录，请核对复权口径")

    return out.reset_index(drop=True)


def adjust_price(df: pd.DataFrame, mode: str = "none") -> pd.DataFrame:
    """按需复权（口径显式传入）。

    mode:
        'none' : 不复权（原样返回）
        'qfq'  : 前复权 —— 历史价乘以 adj_factor / latest_adj_factor
        'hfq'  : 后复权 —— 历史价乘以 adj_factor
    """
    if mode == "none":
        return df.copy()

    out = df.copy()
    if "adj_factor" not in out.columns:
        raise ValueError("缺少 adj_factor 列，无法复权")

    latest = out["adj_factor"].iloc[-1] if len(out) else 1.0
    price_cols = ["open", "high", "low", "close"]
    if "prev_close" in out.columns:
        price_cols.append("prev_close")

    if mode == "qfq":
        ratio = out["adj_factor"] / latest
    elif mode == "hfq":
        ratio = out["adj_factor"]
    else:
        raise ValueError(f"未知复权模式: {mode}（可选 none/qfq/hfq）")

    for col in price_cols:
        out[col] = out[col] * ratio
    return out
