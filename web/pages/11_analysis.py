"""绩效分析页：策略净值 vs 基准（沪深300/上证）+ 风险指标全景 + 月度热力图 + 日收益分布。

业界标配（调研 QUANTAXIS / vn.py / QuantOL 等后补齐）：
- 净值 vs 基准对比（新浪源拉取，本地缓存 data/bars/index_*.csv）
- 相对收益 / 超额收益
- VaR95 / CVaR95 / Alpha / Beta / 信息比率 / 卡玛 / 月度胜率
- 日收益分布直方图（正态参考线）
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from web import charts
from web.i18n import lang_selector, t
from web.theme import (ACCENT, BORDER, DOWN, GOLD, TEXT, TEXT_DIM, UP,
                       inject_css, kpi_card, kpi_grid)

lang_selector()
st.set_page_config(page_title="绩效分析 · QUANT TERMINAL", layout="wide")
st.markdown(inject_css(), unsafe_allow_html=True)

st.markdown(f"""
<div class="page-title">◈ {t("绩效分析")} / PERFORMANCE ANALYSIS</div>
<div style="color:{TEXT_DIM}; font-size:12px; margin-bottom:10px;">
    {t("净值对比基准")} · VaR/CVaR · Alpha/Beta · {t("月度收益热力图")} · {t("日收益分布")}</div>
""", unsafe_allow_html=True)

BENCH_DIR = ROOT / "data" / "bars"
BENCH: dict[str, str] = {
    "sh000300": "沪深300",
    "sh000001": "上证指数",
}


# ── 数据加载 ─────────────────────────────────────────────

@st.cache_data(ttl=600, show_spinner="加载净值…")
def load_equity() -> pd.Series:
    p = ROOT / "report" / "equity.csv"
    if not p.exists():
        return pd.Series(dtype=float)
    df = pd.read_csv(p, parse_dates=["date"]).set_index("date")["equity"]
    return df[df > 0].astype(float)


@st.cache_data(ttl=120, show_spinner="加载实盘净值…")
def load_paper_equity() -> pd.Series:
    """模拟盘实盘净值：策略市值口径（100 万重建仓位），自 2026-11-12 重建日起。"""
    p = ROOT / "data" / "paper_equity.csv"
    if not p.exists():
        return pd.Series(dtype=float)
    try:
        df = pd.read_csv(p, parse_dates=["date"]).set_index("date")
        # 口径：优先策略市值（100 万仓位净值变化），缺失退化到总资产
        col = "strategy_mv" if "strategy_mv" in df.columns else "total_asset"
        s = df[col]
        return s[s > 0].astype(float)
    except Exception:  # noqa: BLE001
        return pd.Series(dtype=float)


@st.cache_data(ttl=3600, show_spinner="拉取基准…")
def load_benchmark(sym: str) -> pd.Series:
    """基准指数日线（新浪源）。先读本地缓存，缺失或过期时在线拉取。"""
    cache = BENCH_DIR / f"index_{sym}.csv"
    today = pd.Timestamp.now().normalize()
    if cache.exists():
        try:
            df = pd.read_csv(cache, parse_dates=["date"]).set_index("date")["close"]
            if len(df) and df.index.max() >= today - pd.Timedelta(days=10):
                return df.astype(float)
        except Exception:  # noqa: BLE001
            pass
    try:
        import akshare as ak
        raw = ak.stock_zh_index_daily(symbol=sym)
        df = raw[["date", "close"]].copy()
        df["date"] = pd.to_datetime(df["date"])
        df = df.drop_duplicates("date").set_index("date")["close"].astype(float)
        if len(df):
            BENCH_DIR.mkdir(parents=True, exist_ok=True)
            df.to_frame("close").to_csv(cache)
        return df
    except Exception:  # noqa: BLE001
        if cache.exists():  # 在线失败回退旧缓存
            return pd.read_csv(cache, parse_dates=["date"]).set_index("date")["close"].astype(float)
        return pd.Series(dtype=float)


def perf_metrics(eq: pd.Series, bench: pd.Series | None = None,
                 rf: float = 0.015) -> dict:
    """核心绩效指标：收益/回撤/夏普/索提诺/卡玛/VaR/CVaR/(+基准时 Alpha/Beta/IR)。

    小样本（实盘初期 < 30 天）时方差类指标标记 unstable=True。
    """
    ret = eq.pct_change().dropna()
    n = len(eq)
    out: dict = {"n_days": n, "unstable": n < 30}
    if n < 2 or ret.empty:
        return out
    total = eq.iloc[-1] / eq.iloc[0] - 1
    years = max((eq.index[-1] - eq.index[0]).days / 365.25, 1e-9)
    ann_ret = (1 + total) ** (1 / years) - 1
    ann_vol = ret.std(ddof=1) * np.sqrt(252)
    dd = eq / eq.cummax() - 1
    max_dd = float(dd.min())
    var95 = float(np.percentile(ret, 5))
    cvar95 = float(ret[ret <= var95].mean())
    var99 = float(np.percentile(ret, 1))
    cvar99 = float(ret[ret <= var99].mean())
    downside = ret[ret < 0].std(ddof=1) * np.sqrt(252) if (ret < 0).any() else np.nan
    sharpe = (ann_ret - rf) / ann_vol if ann_vol > 0 else np.nan
    sortino = (ann_ret - rf) / downside if downside and downside > 0 else np.nan
    calmar = ann_ret / abs(max_dd) if max_dd < 0 else np.nan
    monthly = eq.resample("ME").last().pct_change().dropna()
    win_m = float((monthly > 0).mean()) if len(monthly) else np.nan

    out.update({
        "total": float(total), "ann_ret": float(ann_ret), "ann_vol": float(ann_vol),
        "max_dd": max_dd, "sharpe": float(sharpe), "sortino": float(sortino) if sortino == sortino else None,
        "calmar": float(calmar) if calmar == calmar else None,
        "var95": var95, "cvar95": cvar95, "var99": var99, "cvar99": cvar99,
        "win_m": win_m,
    })

    if bench is not None and len(bench):
        dfb = pd.DataFrame({"eq": eq}).join(
            pd.DataFrame({"b": bench}), how="inner").dropna()
        if len(dfb) >= 3:
            r = dfb["eq"].pct_change().dropna()
            rb = dfb["b"].pct_change().dropna()
            # 对齐两个序列
            idx = r.index.intersection(rb.index)
            r, rb = r[idx], rb[idx]
            if len(r) >= 3:
                cov = np.cov(r, rb, ddof=1)
                beta = cov[0, 1] / cov[1, 1] if cov[1, 1] != 0 else np.nan
                alpha = (1 + r.mean() * 252) / (1 + rb.mean() * 252) - 1  # 年化超额
                te = (r - rb).std(ddof=1) * np.sqrt(252)
                ir = (r - rb).mean() * 252 / te if te > 0 else np.nan
                out.update({
                    "bench_total": float(dfb["b"].iloc[-1] / dfb["b"].iloc[0] - 1),
                    "alpha": float(alpha), "beta": float(beta), "ir": float(ir) if ir == ir else None,
                })
    return out


# ── 页面主体 ─────────────────────────────────────────────

paper_eq = load_paper_equity()
has_paper = len(paper_eq) >= 2

col_pick, col_b = st.columns([2, 2])
with col_b:
    bench_sym = st.selectbox(t("基准"), list(BENCH), index=0, format_func=lambda s: BENCH[s])
with col_pick:
    if has_paper:
        view_labels = {t("回测重放"): "backtest", t("实盘拟合"): "paper"}
        view = st.radio(t("净值视图"), list(view_labels), index=1,
                        format_func=lambda x: x, label_visibility="visible",
                        horizontal=True)
        view = view_labels[view]
    else:
        view = "backtest"

eq = load_equity()
if view == "paper":
    eq = paper_eq
if eq.empty:
    st.warning("暂无净值数据。运行 python main.py run-paper 生成。")
    st.stop()

if view == "paper" and len(eq) < 10:
    st.info(f"{t('实盘拟合')}：{t('模拟盘正式运行自')} 2026-11-12（100 万仓位重建，策略市值口径）"
            f"（{len(eq)} {t('个交易日')}）——{t('数据积累中，指标需 ≥10 天后稳定')}")

bench = load_benchmark(bench_sym)
m = perf_metrics(eq, bench if bench is not None and len(bench) else None)

# ── KPI 总览 ──
has_bench = "bench_total" in m
unstable_tag = f" · ⚠ {t('样本不足30天')}" if m.get("unstable") else ""
st.markdown(f'<div class="panel-title">{t("收益与风险总览")} / OVERVIEW</div>',
            unsafe_allow_html=True)
st.markdown(kpi_grid([
    kpi_card(t("累计收益"), f"{m.get('total', 0):.2%}",
             f"{m.get('n_days', 0)} {t('个交易日')}",
             cls="kpi-up" if m.get("total", 0) >= 0 else "kpi-down"),
    kpi_card(t("年化收益"), f"{m.get('ann_ret', 0):.2%}",
             f"RF 1.5%{unstable_tag}", cls="kpi-up" if m.get("ann_ret", 0) >= 0 else "kpi-down"),
    kpi_card(t("最大回撤"), f"{m.get('max_dd', 0):.2%}", t("水下曲线峰值"),
             cls="kpi-down" if m.get("max_dd", 0) < 0 else None),
    kpi_card(t("夏普比率"), f"{m.get('sharpe', float('nan')):.3f}", "Ann / RF 1.5%"),
    kpi_card(t("索提诺比率") if "索提诺比率" else "", f"{m.get('sortino') or float('nan'):.3f}",
             "下行波动口径") if "sortino" in m else None,
    kpi_card(t("卡玛比率"), f"{m.get('calmar') or float('nan'):.2f}",
             "年化/|最大回撤|") if "calmar" in m else None,
    kpi_card(t("月度胜率"), f"{(m.get('win_m') or 0):.0%}", "月末净值口径") if "win_m" in m else None,
    kpi_card(t("年化波动"), f"{m.get('ann_vol', 0):.2%}", "日收益×√252"),
]), unsafe_allow_html=True)

if has_bench:
    st.markdown(kpi_grid([
        kpi_card(f"{t('基准收益')}（{BENCH[bench_sym]}）",
                 f"{m['bench_total']:.2%}", t("新浪源·本地缓存")),
        kpi_card(t("超额收益"), f"{m['total'] - m['bench_total']:.2%}",
                 t("策略-基准（区间）"),
                 cls="kpi-up" if m['total'] >= m['bench_total'] else "kpi-down"),
        kpi_card("Alpha（年化）", f"{m.get('alpha', float('nan')):.2%}",
                 "相对基准日频回归"),
        kpi_card("Beta", f"{m.get('beta', float('nan')):.2f}", "系统性暴露"),
        kpi_card(t("信息比率"), f"{m.get('ir') or float('nan'):.2f}",
                 "超额收益/跟踪误差"),
    ]), unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True)

# ── 净值 vs 基准（归一化对比） ──
st.markdown(f'<div class="panel-title">{t("净值对比基准")} / EQUITY vs BENCHMARK</div>',
            unsafe_allow_html=True)
if bench is not None and len(bench):
    with st.spinner(t("对齐中…")):
        dfb = pd.DataFrame({"eq": eq}).join(pd.DataFrame({"b": bench}), how="inner").dropna()
    if len(dfb) > 10:
        norm_eq = dfb["eq"] / dfb["eq"].iloc[0]
        norm_b = dfb["b"] / dfb["b"].iloc[0]
        import plotly.graph_objects as go
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=norm_eq.index, y=norm_eq.values, name=t("策略净值"),
            line=dict(color=ACCENT, width=2),
            hovertemplate="%{x|%Y-%m-%d}<br>%{y:.4f}<extra>" + t("策略") + "</extra>"))
        fig.add_trace(go.Scatter(
            x=norm_b.index, y=norm_b.values, name=f"{BENCH[bench_sym]}",
            line=dict(color=GOLD, width=1.6, dash="dot"),
            hovertemplate="%{x|%Y-%m-%d}<br>%{y:.4f}<extra>" + BENCH[bench_sym] + "</extra>"))
        # 超额收益面积（次轴）
        fig.add_trace(go.Scatter(
            x=norm_eq.index, y=(norm_eq - norm_b).values, name=t("超额收益"),
            line=dict(color="rgba(148,163,184,.7)", width=1),
            fill="tozeroy", fillcolor="rgba(148,163,184,.08)",
            hovertemplate="%{x|%Y-%m-%d}<br>%{y:.2%}<extra>" + t("超额") + "</extra>"))
        fig.update_layout(
            margin=dict(l=10, r=10, t=30, b=10), height=420,
            hovermode="x unified", dragmode="pan",
            legend=dict(orientation="h", y=1.08, font=dict(color=TEXT_DIM)),
        )
        fig.update_xaxes(showgrid=True, gridcolor=BORDER)
        fig.update_yaxes(showgrid=True, gridcolor=BORDER, tickformat=".2f")
        st.plotly_chart(fig, use_container_width=True)
        st.caption(t("归一化口径说明"))
    else:
        st.info(t("基准重叠不足"))
else:
    st.info("基准数据不可用（新浪源拉取失败且无本地缓存）——仅展示策略自身净值")
    st.plotly_chart(charts.equity_chart(eq), use_container_width=True)

# ── 风险指标（VaR/CVaR 表 + 回撤曲线） ──
c1, c2 = st.columns([3, 2])
with c1:
    st.markdown(f'<div class="panel-title">{t("回撤曲线")} / UNDERWATER</div>',
                unsafe_allow_html=True)
    st.plotly_chart(charts.drawdown_chart(eq), use_container_width=True)
with c2:
    st.markdown(f'<div class="panel-title">{t("尾部风险")} / TAIL RISK</div>',
                unsafe_allow_html=True)
    data = [
        ["VaR 95%", m.get("var95"), t("日损失超过此值的概率为 5%")],
        ["CVaR 95%", m.get("cvar95"), t("最坏 5% 日均损失")],
        ["VaR 99%", m.get("var99"), t("日损失超过此值的概率为 1%")],
        ["CVaR 99%", m.get("cvar99"), t("最坏 1% 日均损失")],
    ]
    st.markdown(
        "<table style='width:100%; border-collapse:collapse; font-size:13px;'>"
        + "".join(
            f"<tr><td style='padding:8px 10px; border-bottom:1px solid {BORDER};'>{k}</td>"
            f"<td style='padding:8px 10px; border-bottom:1px solid {BORDER}; "
            f"text-align:right; color:{DOWN if (v or 0) < 0 else UP}; "
            f"font-family:monospace;'>{v:.2%}</td></tr>"
            f"<tr><td colspan=2 style='padding:2px 10px 10px; color:{TEXT_DIM}; "
            f"font-size:11px;'>{d}</td></tr>"
            for k, v, d in data if v is not None
        ) + "</table>", unsafe_allow_html=True)
    st.caption("历史模拟法 · 日收益分布 · 非参数估计")

st.markdown("<br>", unsafe_allow_html=True)

# ── 月度热力图 + 日收益分布 ──
c3, c4 = st.columns(2)
with c3:
    st.markdown(f'<div class="panel-title">{t("月度收益热力图")} / MONTHLY RETURNS</div>',
                unsafe_allow_html=True)
    st.plotly_chart(charts.monthly_heatmap(eq), use_container_width=True)
with c4:
    st.markdown(f'<div class="panel-title">{t("日收益分布")} / DAILY RETURN DIST</div>',
                unsafe_allow_html=True)
    ret = eq.pct_change().dropna()
    if len(ret) > 10:
        import plotly.graph_objects as go
        fig = go.Figure()
        fig.add_trace(go.Histogram(
            x=ret.values * 100, nbinsx=40,
            marker=dict(color=ACCENT, opacity=0.75,
                        line=dict(color=BORDER, width=0.5)),
            hovertemplate=t("区间") + " [%{x:.2f}%, %{x:.2f}%+w]<br>"
                         + t("天数") + " %{y}<extra></extra>"))
        mu, sigma = float(ret.mean() * 100), float(ret.std(ddof=1) * 100)
        xs = np.linspace(ret.min() * 100, ret.max() * 100, 200)
        fig.add_trace(go.Scatter(
            x=xs, y=(1 / (sigma * np.sqrt(2 * np.pi))
                     * np.exp(-((xs - mu) ** 2) / (2 * sigma ** 2))) * len(ret) * 100 / 40,
            mode="lines", name=t("正态参考"),
            line=dict(color=GOLD, width=1.5, dash="dot"),
            hoverinfo="skip"))
        fig.update_layout(
            margin=dict(l=10, r=10, t=30, b=10), height=340,
            bargap=0.03, showlegend=False,
            xaxis=dict(title=t("日收益") + " (%)", tickformat=".1f"),
            yaxis=dict(title=t("天数")),
        )
        fig.update_xaxes(showgrid=True, gridcolor=BORDER)
        fig.update_yaxes(showgrid=True, gridcolor=BORDER)
        st.plotly_chart(fig, use_container_width=True)
        skew = float(((ret - ret.mean()) ** 3).mean() / ret.std(ddof=1) ** 3)
        kurt = float(((ret - ret.mean()) ** 4).mean() / ret.std(ddof=1) ** 4 - 3)
        st.caption(f"μ={mu:.3f}% σ={sigma:.3f}% · {t('偏度')} {skew:+.2f} · "
                   f"{t('超额峰度')} {kurt:+.2f} · {t('尖峰厚尾提示')}")

st.caption(f"{t('数据区间')} {eq.index[0]:%Y-%m-%d} ~ {eq.index[-1]:%Y-%m-%d} · "
          f"{t('基准源')} 新浪财经 · {t('缓存')} data/bars/index_{bench_sym}.csv · "
          f"RF=1.5%")
