"""
绩效报告模块（M6）：Markdown 报告生成
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from backtest.metrics import compute_metrics, max_drawdown


def monthly_returns_table(equity: pd.Series) -> pd.DataFrame:
    """月度收益表（行=年份，列=1-12月，值=百分比）。"""
    eq = pd.Series(equity, dtype=float).dropna()
    if len(eq) < 2:
        return pd.DataFrame()
    monthly = eq.resample("ME").last()
    ret = monthly.pct_change() * 100
    # 首月
    first_val = eq[eq.index <= monthly.index[0]]
    if len(first_val) > 1:
        ret.iloc[0] = (first_val.iloc[-1] / first_val.iloc[0] - 1.0) * 100
    table = pd.DataFrame({
        "year": ret.index.year,
        "month": ret.index.month,
        "ret": ret.values,
    }).pivot_table(index="year", columns="month", values="ret")
    table.columns = [f"{m}月" for m in table.columns]
    table["全年"] = table.mean(axis=1, skipna=True)
    return table.round(2)


def generate_report(
    equity: pd.Series,
    trades: list | None = None,
    benchmark: pd.Series | None = None,
    title: str = "回测报告",
    out_path: str | Path = "report/report.md",
    chart_paths: dict | None = None,
) -> Path:
    """生成 Markdown 绩效报告。"""
    eq = pd.Series(equity, dtype=float).dropna()
    metrics = compute_metrics(eq, benchmark=benchmark)
    mdd = max_drawdown(eq)

    lines = [f"# {title}", ""]
    lines += [f"- 区间：{eq.index[0].date()} ~ {eq.index[-1].date()}（{len(eq)} 个交易日）", ""]

    # 核心指标
    lines += ["## 核心指标", ""]
    lines += ["| 指标 | 值 |", "|---|---|"]
    lines += [f"| 累计收益 | {metrics['total_return']:+.2%} |"]
    lines += [f"| 年化收益 | {metrics['annual_return']:+.2%} |"]
    lines += [f"| 年化波动 | {metrics['volatility']:.2%} |"]
    lines += [f"| 最大回撤 | {metrics['max_drawdown']:.2%} |"]
    lines += [f"| 夏普比率 | {metrics['sharpe']:.3f} |"]
    lines += [f"| 卡玛比率 | {metrics['calmar']:.3f} |"]
    lines += [f"| 日胜率 | {metrics['win_rate']:.2%} |"]
    if "ir" in metrics:
        lines += [f"| 信息比率 | {metrics['ir']:.3f} |"]
        lines += [f"| 超额收益 | {metrics['excess_return']:+.2%} |"]
    lines += [""]

    # 月度收益表
    monthly = monthly_returns_table(eq)
    if not monthly.empty:
        lines += ["## 月度收益 (%)", "", monthly.to_markdown(), ""]

    # 交易统计
    if trades:
        trades_df = pd.DataFrame(trades)
        n_buys = int((trades_df["side"] == "buy").sum()) if "side" in trades_df else 0
        n_sells = int((trades_df["side"] == "sell").sum()) if "side" in trades_df else 0
        total_fee = float(trades_df["fee"].sum()) if "fee" in trades_df else 0.0
        lines += ["## 交易统计", ""]
        lines += [f"- 成交笔数：{len(trades_df)}（买入 {n_buys} / 卖出 {n_sells}）"]
        lines += [f"- 总费用：{total_fee:,.0f}"]
        lines += [""]

    # 图表
    if chart_paths:
        lines += ["## 图表", ""]
        for name, p in chart_paths.items():
            lines += [f"### {name}", "", f"![{name}]({Path(p).as_posix()})", ""]

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines), encoding="utf-8")
    return out
