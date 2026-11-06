"""
绩效计算模块（难点模块之三）

职责：由净值/市值序列计算绩效指标。

红线（智谱接续开发务必遵守）：
1. 年化收益按「实际交易日数」折算，禁止简单乘以周期。
2. 最大回撤用净值曲线的 cummax 计算，禁止用首末价格近似。
3. 夏普/波动率用「日收益序列」的标准差，无风险利率可配置。
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def max_drawdown(equity: pd.Series) -> float:
    """最大回撤（负值，如 -0.25 表示 -25%）。"""
    equity = pd.Series(equity, dtype=float)
    if len(equity) == 0:
        return 0.0
    cummax = equity.cummax()
    drawdown = equity / cummax - 1.0
    return float(drawdown.min())


def compute_metrics(
    equity: pd.Series,
    periods_per_year: int = 252,
    risk_free_rate: float = 0.0,
    benchmark: pd.Series | None = None,
) -> dict:
    """计算绩效指标。

    参数
    ----
    equity : 组合净值/市值序列（索引建议为日期）
    periods_per_year : 年化周期数（A 股日频约 252）
    risk_free_rate : 年化无风险利率（默认 0）
    benchmark : 基准净值序列（可选，用于信息比率/超额收益）

    返回 dict，含：total_return / annual_return / volatility / sharpe /
    calmar / max_drawdown / win_rate / 以及可选 ir / excess_return
    """
    equity = pd.Series(equity, dtype=float).dropna()
    if len(equity) < 2:
        return {"total_return": 0.0, "annual_return": 0.0, "volatility": 0.0,
                "sharpe": 0.0, "calmar": 0.0, "max_drawdown": 0.0, "win_rate": 0.0}

    returns = equity.pct_change().dropna()
    n_days = len(equity) - 1  # 收益区间天数

    # 总收益 / 年化收益
    total_return = float(equity.iloc[-1] / equity.iloc[0] - 1.0)
    if equity.iloc[0] > 0 and n_days > 0:
        annual_return = float((equity.iloc[-1] / equity.iloc[0]) ** (periods_per_year / n_days) - 1.0)
    else:
        annual_return = 0.0

    # 波动率（年化）
    daily_std = float(returns.std(ddof=1)) if len(returns) > 1 else 0.0
    volatility = daily_std * np.sqrt(periods_per_year)

    # 夏普
    daily_rf = risk_free_rate / periods_per_year
    if len(returns) > 1 and daily_std > 0:
        sharpe = float((returns.mean() - daily_rf) / daily_std * np.sqrt(periods_per_year))
    else:
        sharpe = 0.0

    # 最大回撤 / 卡玛
    mdd = max_drawdown(equity)
    calmar = float(annual_return / abs(mdd)) if mdd < 0 else 0.0

    # 胜率（日收益 > 0 的占比）
    win_rate = float((returns > 0).mean()) if len(returns) > 0 else 0.0

    result = {
        "total_return": total_return,
        "annual_return": annual_return,
        "volatility": volatility,
        "sharpe": sharpe,
        "calmar": calmar,
        "max_drawdown": mdd,
        "win_rate": win_rate,
    }

    # 可选：基准对比
    if benchmark is not None:
        bench = pd.Series(benchmark, dtype=float).reindex(equity.index).dropna()
        if len(bench) > 1:
            bench_ret = bench.pct_change().dropna()
            aligned = returns.reindex(bench_ret.index).dropna()
            bench_aligned = bench_ret.reindex(aligned.index)
            excess = aligned - bench_aligned
            result["excess_return"] = float(
                (equity.iloc[-1] / equity.iloc[0]) - (bench.iloc[-1] / bench.iloc[0])
            )
            if len(excess) > 1 and float(excess.std(ddof=1)) > 0:
                result["ir"] = float(
                    excess.mean() / excess.std(ddof=1) * np.sqrt(periods_per_year)
                )
            else:
                result["ir"] = 0.0
    return result
