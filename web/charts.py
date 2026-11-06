"""图表工厂：Plotly 交互图（净值/回撤/月度热力图/K线/因子条形图）"""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from web.theme import (ACCENT, ACCENT_2, BG, BORDER, DOWN, GOLD, NASDAQ,
                       PANEL, TEXT, TEXT_DIM, UP)


def equity_chart(equity: pd.Series, initial: float = 1_000_000.0) -> go.Figure:
    """净值曲线：面积填充 + 基准线 + 区间缩放。"""
    fig = go.Figure()
    x = pd.to_datetime(equity.index)
    y = equity.values.astype(float)
    ret = y[-1] / y[0] - 1
    color = UP if ret >= 0 else DOWN

    fig.add_trace(go.Scatter(
        x=x, y=y, name="净值",
        line=dict(color=color, width=2),
        fill="tozeroy",
        fillcolor=f"rgba(248,113,113,.08)" if ret >= 0 else "rgba(74,222,128,.08)",
        hovertemplate="%{x|%Y-%m-%d}<br>净值 %{y:,.0f}<extra></extra>",
    ))
    fig.add_hline(y=initial, line_dash="dot", line_color=TEXT_DIM,
                  annotation_text="初始资金", annotation_font_color=TEXT_DIM)
    fig.update_layout(
        margin=dict(l=10, r=10, t=30, b=10),
        height=380,
        xaxis=dict(rangeslider=dict(visible=False)),
        hovermode="x unified",
        dragmode="pan",
    )
    fig.update_xaxes(showgrid=True, gridcolor=BORDER)
    fig.update_yaxes(showgrid=True, gridcolor=BORDER, tickformat=",.0f")
    return fig


def drawdown_chart(equity: pd.Series) -> go.Figure:
    """水下回撤曲线（绿色填充向下）。"""
    x = pd.to_datetime(equity.index)
    dd = equity.values / pd.Series(equity.values).cummax() - 1

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=x, y=dd.values, name="回撤",
        line=dict(color=DOWN, width=1.6),
        fill="tozeroy", fillcolor="rgba(74,222,128,.12)",
        hovertemplate="%{x|%Y-%m-%d}<br>回撤 %{y:.2%}<extra></extra>",
    ))
    fig.update_layout(
        margin=dict(l=10, r=10, t=30, b=10), height=240,
        hovermode="x unified", dragmode="pan",
        yaxis=dict(tickformat=".0%"),
    )
    fig.update_xaxes(showgrid=True, gridcolor=BORDER)
    fig.update_yaxes(showgrid=True, gridcolor=BORDER)
    return fig


def monthly_heatmap(equity: pd.Series) -> go.Figure:
    """月度收益热力图（红涨绿跌）。"""
    s = equity.copy()
    s.index = pd.to_datetime(s.index)
    monthly = s.resample("ME").last()
    if len(monthly) < 2:
        return go.Figure()
    mret = monthly.pct_change().dropna()
    pivot = pd.DataFrame({
        "year": mret.index.year,
        "month": mret.index.month,
        "ret": mret.values,
    }).pivot_table(index="year", columns="month", values="ret")

    fig = go.Figure(go.Heatmap(
        z=pivot.values,
        x=[f"{m}月" for m in pivot.columns],
        y=pivot.index.astype(str),
        colorscale=[[0, DOWN], [0.5, "#0A0E17"], [1, UP]],
        zmid=0,
        text=[[f"{v:.1%}" if pd.notna(v) else "" for v in row] for row in pivot.values],
        texttemplate="%{text}",
        textfont=dict(size=11),
        hovertemplate="%{y}年 %{x}<br>%{z:.2%}<extra></extra>",
        colorbar=dict(tickformat=".0%", thickness=10),
    ))
    fig.update_layout(
        margin=dict(l=10, r=10, t=30, b=10), height=340,
    )
    return fig


def candlestick(df: pd.DataFrame, title: str = "") -> go.Figure:
    """K 线 + 成交量（涨红跌绿）。"""
    d = df.copy()
    d["date"] = pd.to_datetime(d["date"])
    inc = d["close"] >= d["open"]
    colors = [UP if i else DOWN for i in inc]

    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=True,
        row_heights=[0.72, 0.28], vertical_spacing=0.02,
    )
    fig.add_trace(go.Candlestick(
        x=d["date"], open=d["open"], high=d["high"], low=d["low"], close=d["close"],
        increasing=dict(line=dict(color=UP, width=1), fillcolor="rgba(248,113,113,.9)"),
        decreasing=dict(line=dict(color=DOWN, width=1), fillcolor="rgba(74,222,128,.9)"),
        name="K线",
    ), row=1, col=1)
    vol_colors = [UP if (d["close"].iloc[i] >= d["prev_close"].iloc[i] if pd.notna(d["prev_close"].iloc[i]) else True) else DOWN
                  for i in range(len(d))]
    fig.add_trace(go.Bar(
        x=d["date"], y=d["volume"], marker_color=vol_colors, opacity=0.55, name="成交量",
        hovertemplate="%{x|%Y-%m-%d}<br>vol %{y:,.0f}<extra></extra>",
    ), row=2, col=1)

    fig.update_layout(
        margin=dict(l=10, r=10, t=36, b=10), height=460,
        title=dict(text=title, font=dict(size=13)),
        xaxis_rangeslider_visible=False,
        dragmode="pan",
        showlegend=False,
    )
    fig.update_xaxes(showgrid=True, gridcolor=BORDER)
    fig.update_yaxes(showgrid=True, gridcolor=BORDER)
    return fig


def factor_ic_bar(qa: pd.DataFrame) -> go.Figure:
    """因子 IC 条形图（正红负绿，|IC|>0.03 高亮边框）。"""
    d = qa.sort_values("ic_mean")
    colors = [UP if v >= 0 else DOWN for v in d["ic_mean"]]
    fig = go.Figure(go.Bar(
        x=d["ic_mean"], y=d["factor"], orientation="h",
        marker_color=colors,
        text=[f"{v:.4f}" for v in d["ic_mean"]],
        textposition="outside",
        textfont=dict(size=11),
        hovertemplate="%{y}<br>IC %{x:.4f}<extra></extra>",
    ))
    fig.add_vline(x=0.03, line_dash="dot", line_color=GOLD,
                  annotation_text="+0.03", annotation_font_color=GOLD)
    fig.add_vline(x=-0.03, line_dash="dot", line_color=GOLD,
                  annotation_text="-0.03", annotation_font_color=GOLD)
    fig.update_layout(
        margin=dict(l=10, r=40, t=30, b=10), height=360,
        xaxis=dict(tickformat=".3f"),
    )
    fig.update_xaxes(showgrid=True, gridcolor=BORDER)
    fig.update_yaxes(showgrid=True, gridcolor=BORDER)
    return fig


def factor_corr_heatmap(corr: pd.DataFrame) -> go.Figure:
    """因子相关矩阵热力图。"""
    fig = go.Figure(go.Heatmap(
        z=corr.values, x=corr.columns, y=corr.index,
        colorscale=[[0, DOWN], [0.5, "#0A0E17"], [1, UP]], zmid=0,
        text=[[f"{v:.2f}" for v in row] for row in corr.values],
        texttemplate="%{text}",
        textfont=dict(size=10),
        hovertemplate="%{y} × %{x}<br>ρ = %{z:.3f}<extra></extra>",
        colorbar=dict(thickness=10),
    ))
    fig.update_layout(margin=dict(l=10, r=10, t=30, b=10), height=420)
    return fig


def asset_weight_donut(weights: dict, gold: float, nasdaq: float) -> go.Figure:
    """三资产权重环形图（历史权重轨迹可用滑块切换——此处静态快照）。"""
    labels = ["A股持仓", "黄金 ETF", "纳指 ETF", "现金"]
    stock_val = weights.get("stock_value", 0)
    vals = [stock_val, gold, nasdaq, max(weights.get("cash", 0), 0)]
    colors = [ACCENT, GOLD, NASDAQ, "#334155"]

    fig = go.Figure(go.Pie(
        labels=labels, values=vals, hole=0.62,
        marker=dict(colors=colors, line=dict(color=BG, width=2)),
        textinfo="percent", textfont=dict(color=TEXT, size=12),
        hovertemplate="%{label}<br>%{value:,.0f}<extra></extra>",
    ))
    fig.update_layout(
        margin=dict(l=10, r=10, t=30, b=10), height=320,
        showlegend=True,
        legend=dict(orientation="h", y=-0.05, font=dict(color=TEXT_DIM)),
    )
    return fig


def lambda_comparison(results: dict[str, dict]) -> go.Figure:
    """λ 三档对比：收益 vs 回撤散点 + 标注。"""
    fig = go.Figure()
    xs, ys, labels = [], [], []
    for lam, m in results.items():
        xs.append(abs(m.get("max_drawdown", 0)))
        ys.append(m.get("total_return", 0))
        labels.append(f"λ={lam}")

    fig.add_trace(go.Scatter(
        x=xs, y=ys, mode="markers+text",
        marker=dict(size=16, color=[ACCENT, GOLD, UP][:len(xs)],
                    line=dict(color=TEXT, width=1)),
        text=labels, textposition="top center",
        textfont=dict(color=TEXT, size=12),
        hovertemplate="λ=%{text}<br>回撤 %{x:.2%}<br>收益 %{y:.2%}<extra></extra>",
    ))
    fig.update_layout(
        margin=dict(l=10, r=10, t=30, b=10), height=360,
        xaxis=dict(title="最大回撤(绝对值)", tickformat=".0%"),
        yaxis=dict(title="累计收益", tickformat=".0%"),
    )
    fig.update_xaxes(showgrid=True, gridcolor=BORDER)
    fig.update_yaxes(showgrid=True, gridcolor=BORDER)
    return fig


def correlation_gauge(corr_val: float, label: str) -> go.Figure:
    """对冲失效监控表盘（|ρ|>0.5 告警区）。"""
    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=corr_val,
        number=dict(valueformat=".2f", font=dict(color=TEXT)),
        title=dict(text=label, font=dict(size=13, color=TEXT_DIM)),
        gauge=dict(
            axis=dict(range=[-1, 1], tickcolor=TEXT_DIM,
                      tickfont=dict(size=10)),
            bar=dict(color=ACCENT, thickness=0.28),
            steps=[
                dict(range=[-1, -0.5], color="rgba(74,222,128,.25)"),
                dict(range=[-0.5, 0.5], color="rgba(34,211,238,.10)"),
                dict(range=[0.5, 1], color="rgba(248,113,113,.25)"),
            ],
            threshold=dict(line=dict(color=GOLD, width=3),
                           value=min(max(abs(corr_val), -1), 1) if corr_val >= 0 else -min(abs(corr_val), 1)),
        ),
    ))
    fig.update_layout(margin=dict(l=10, r=10, t=40, b=10), height=230)
    return fig
