"""
压力测试 / 场景分析（M6，跨资产对冲策略必修）

借鉴高盛 SecDB「反事实分析」：在软件里模拟损失，比在现实里损失便宜得多。

功能：
1. 历史极端情景回放：2015 股灾 / 2018 贸易战 / 2020 疫情 / 2024 微盘股危机，
   回放组合表现，输出各情景的回撤 / 最大单日亏损。
2. 对冲失效测试（核心）：三资产相关性在系统性危机时可能突变为正（同跌），
   用历史情景验证「分散失效」，而非只看日常相关性。
"""

from __future__ import annotations

import pandas as pd

from backtest.metrics import max_drawdown

# 内置历史极端情景（A 股）
SCENARIOS: dict[str, dict] = {
    "2015_stock_crash":   {"label": "2015 股灾", "start": "2015-06-15", "end": "2015-09-30"},
    "2018_trade_war":     {"label": "2018 贸易战", "start": "2018-03-22", "end": "2018-12-31"},
    "2020_covid":         {"label": "2020 疫情", "start": "2020-02-03", "end": "2020-03-31"},
    "2024_microcap_crisis": {"label": "2024 微盘股流动性危机", "start": "2024-01-01", "end": "2024-02-29"},
}


def scenario_replay(
    equity: pd.Series,
    scenario: dict,
) -> dict:
    """单情景回放：截取情景区间的净值，计算回撤 / 最大单日亏损。"""
    eq = pd.Series(equity, dtype=float)
    idx = pd.DatetimeIndex(eq.index)
    mask = (idx >= scenario["start"]) & (idx <= scenario["end"])
    seg = eq[mask]
    if len(seg) < 2:
        return {
            "label": scenario.get("label", ""),
            "start": scenario["start"], "end": scenario["end"],
            "n_days": len(seg), "return": None, "max_drawdown": None,
            "worst_day": None, "status": "no_data",
        }
    ret = float(seg.iloc[-1] / seg.iloc[0] - 1.0)
    mdd = max_drawdown(seg) if seg.iloc[0] > 0 else 0.0
    daily = seg.pct_change().dropna()
    worst_day = float(daily.min()) if len(daily) else None
    return {
        "label": scenario.get("label", ""),
        "start": scenario["start"], "end": scenario["end"],
        "n_days": len(seg),
        "return": round(ret, 4),
        "max_drawdown": round(mdd, 4),
        "worst_day": round(worst_day, 4) if worst_day is not None else None,
        "status": "ok",
    }


def run_stress_tests(equity: pd.Series, scenarios: dict | None = None) -> pd.DataFrame:
    """全部情景回放，输出压力测试报告表。"""
    scen = scenarios or SCENARIOS
    rows = []
    for name, sc in scen.items():
        r = scenario_replay(equity, sc)
        r["scenario"] = name
        rows.append(r)
    df = pd.DataFrame(rows)
    cols = ["scenario", "label", "start", "end", "n_days", "return", "max_drawdown", "worst_day", "status"]
    return df[[c for c in cols if c in df.columns]]


def hedge_failure_test(
    prices: pd.DataFrame,
    windows: list[tuple[str, str, str]] | None = None,
) -> pd.DataFrame:
    """对冲失效测试：各情景区间内三资产两两相关性。

    正常状态：黄金-A股近零相关（对冲有效）、纳指-A股低正（分散有效）。
    失效状态：危机时相关性飙正（同跌）——2020 疫情纳指-A股 0.691 实证。

    参数
    ----
    prices : DataFrame(index=date, columns=[stock, gold, nasdaq])
    windows : [(name, start, end)]，默认用 SCENARIOS
    """
    if windows is None:
        windows = [(name, sc["start"], sc["end"]) for name, sc in SCENARIOS.items()]

    rets = prices[["stock", "gold", "nasdaq"]].pct_change()
    rows = []
    for name, start, end in windows:
        seg = rets.loc[start:end].dropna()
        if len(seg) < 10:
            rows.append({"scenario": name, "n_days": len(seg),
                         "gold_stock_corr": None, "nasdaq_stock_corr": None,
                         "co_move_days": None, "status": "no_data"})
            continue
        gs = seg["gold"].corr(seg["stock"])
        ns = seg["nasdaq"].corr(seg["stock"])
        # 同跌天数占比（三资产日收益同号为负的天数 / 总天数）
        co = ((seg < 0).all(axis=1)).mean()
        rows.append({
            "scenario": name,
            "label": SCENARIOS.get(name, {}).get("label", name),
            "n_days": len(seg),
            "gold_stock_corr": round(float(gs), 3),
            "nasdaq_stock_corr": round(float(ns), 3),
            "co_move_down_pct": round(float(co), 3),
            "status": "ok",
        })
    return pd.DataFrame(rows)


def full_stress_report(equity: pd.Series, prices: pd.DataFrame) -> dict:
    """完整压力测试报告：情景回放 + 对冲失效。"""
    replay = run_stress_tests(equity)
    failure = hedge_failure_test(prices)
    return {"scenario_replay": replay, "hedge_failure": failure}
