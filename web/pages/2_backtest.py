"""回测报告页（终端风格重做：交互图表 + λ 对比 + K线浏览）"""
import sys
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from web.theme import ACCENT, GOLD, TEXT_DIM, inject_css, kpi_card, kpi_grid
from web.i18n import t

st.set_page_config(page_title="回测报告 · QUANT TERMINAL", layout="wide")
st.markdown(inject_css(), unsafe_allow_html=True)

from web.charts import (candlestick, drawdown_chart, equity_chart,
                        lambda_comparison, monthly_heatmap)

st.markdown(f"""
<div class="page-title">◈ {t("回测报告")} / BACKTEST REPORT</div>
<div style="color:{TEXT_DIM}; font-size:12px; margin-bottom:10px;">{t("净值 · 回撤 · 多策略横向对比 · λ 三档对比 · 资产K线")}</div>
""", unsafe_allow_html=True)


@st.cache_data(ttl=60)
def load_equity() -> pd.Series:
    f = ROOT / "report" / "equity.csv"
    if not f.exists():
        return pd.Series(dtype=float)
    return pd.read_csv(f, parse_dates=["date"]).set_index("date")["equity"]


eq = load_equity()
if eq.empty:
    st.info("暂无回测结果。运行 python main.py backtest --strategy cross_asset 生成。")
    st.stop()

# ── KPI 摘要 ──
total_ret = eq.iloc[-1] / eq.iloc[0] - 1
dd = (eq / eq.cummax() - 1).min()
ann_ret = (eq.iloc[-1] / eq.iloc[0]) ** (252 / max(len(eq), 1)) - 1
ann_vol = eq.pct_change().std() * (252 ** 0.5)
sharpe = (ann_ret - 0.02) / ann_vol if ann_vol > 0 else 0

st.markdown('<div class="panel-title">PERFORMANCE / 绩效总览</div>', unsafe_allow_html=True)
st.markdown(kpi_grid([
    kpi_card("累计收益", f"{total_ret:+.2%}", f"{len(eq)} 个交易日",
             cls="kpi-up" if total_ret >= 0 else "kpi-down"),
    kpi_card("年化收益", f"{ann_ret:+.2%}", cls="kpi-up" if ann_ret >= 0 else "kpi-down"),
    kpi_card("最大回撤", f"{dd:.2%}", cls="kpi-down"),
    kpi_card("夏普比率", f"{sharpe:.3f}", "rf = 2%"),
    kpi_card("年化波动", f"{ann_vol:.2%}"),
]), unsafe_allow_html=True)

# ── 净值 + 回撤 ──
c1, c2 = st.columns([2.2, 1])
with c1:
    st.markdown('<div class="panel-title">EQUITY CURVE / 净值</div>', unsafe_allow_html=True)
    st.plotly_chart(equity_chart(eq, initial=float(eq.iloc[0])),
                    use_container_width=True, config={"displayModeBar": False})
with c2:
    st.markdown('<div class="panel-title">DRAWDOWN / 水下</div>', unsafe_allow_html=True)
    st.plotly_chart(drawdown_chart(eq), use_container_width=True,
                    config={"displayModeBar": False})

# ── 月度热力图 ──
st.markdown('<div class="panel-title">MONTHLY RETURNS / 月度收益热力</div>', unsafe_allow_html=True)
st.plotly_chart(monthly_heatmap(eq), use_container_width=True,
                 config={"displayModeBar": False})

st.divider()

# ── 多策略横向对比（对冲 vs 非对冲，读 report/runs/ 各策略最新归档）──
st.markdown('<div class="panel-title">STRATEGY COMPARISON / 多策略横向对比</div>',
            unsafe_allow_html=True)


@st.cache_data(ttl=60)
def load_strategy_runs() -> dict:
    """从 report/runs/ 读各策略最新一次归档（多策略对比 + λ 三档共用数据源）。"""
    import json

    runs_dir = ROOT / "report" / "runs"
    if not runs_dir.exists():
        return {}
    by_strat: dict = {}
    for run_dir in sorted(runs_dir.iterdir()):
        meta_file = run_dir / "run.json"
        if not meta_file.exists():
            continue
        try:
            meta = json.loads(meta_file.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        strat = meta.get("strategy")
        if not strat:
            continue
        rec = {
            "_dir": run_dir.name, "name": meta.get("strategy_name", strat),
            "kind": meta.get("kind", ""), "lam": meta.get("lam"),
            "total_return": meta.get("total_return"),
            "annual_return": meta.get("annual_return"),
            "max_drawdown": meta.get("max_drawdown"),
            "sharpe": meta.get("sharpe"), "calmar": meta.get("calmar"),
            "trades": meta.get("n_trades"), "n_assets": meta.get("n_assets"),
        }
        # 同策略取最新（目录名含时间戳，字典序即时间序）
        if strat not in by_strat or run_dir.name > by_strat[strat]["_dir"]:
            by_strat[strat] = rec
    return by_strat


@st.cache_data(ttl=60)
def load_compare_csv() -> "pd.DataFrame":
    """读 backtest --strategy all 的汇总对比（report/compare/all_compare.csv）。"""
    f = ROOT / "report" / "compare" / "all_compare.csv"
    if not f.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(f)
    except Exception:  # noqa: BLE001
        return pd.DataFrame()


STRAT_LABEL = {
    "cross_asset": "跨资产对冲(λ并轨)", "equal_weight": "等权再平衡",
    "risk_parity": "风险平价", "stock_only": "多因子纯股票", "etf_momentum": "ETF动量轮动",
}
KIND_COLOR = {"对冲": ACCENT, "对冲基准": "#f59e0b", "非对冲": GOLD}


all_runs = load_strategy_runs()
cmp_df = load_compare_csv()
if not all_runs and cmp_df.empty:
    st.info("暂无多策略运行归档。运行 python main.py backtest --strategy all 一键生成对比。")
    st.stop()

# ── 对比表（KPI 横向 + 类型徽标）──
rows = []
order = ["cross_asset", "equal_weight", "risk_parity", "stock_only", "etf_momentum"]
for strat in order:
    if strat not in all_runs:
        continue
    r = all_runs[strat]
    label = f"{r['name']}" + (f" λ={r['lam']}" if r.get("lam") is not None else "")
    rows.append({
        "策略": label, "类型": r["kind"], "累计收益": r["total_return"],
        "年化": r["annual_return"], "最大回撤": r["max_drawdown"],
        "夏普": r["sharpe"], "卡玛": r["calmar"], "成交笔数": r["trades"],
    })
cmp_tbl = pd.DataFrame(rows)
if not cmp_tbl.empty:
    # 按累计收益降序
    cmp_tbl = cmp_tbl.sort_values("累计收益", ascending=False).reset_index(drop=True)
    st.dataframe(
        cmp_tbl.style.format({
            "累计收益": "{:+.2%}", "年化": "{:+.2%}", "最大回撤": "{:.2%}",
            "夏普": "{:.3f}", "卡玛": "{:.3f}", "成交笔数": "{:d}",
        }),
        use_container_width=True, hide_index=True,
    )
    best = cmp_tbl.iloc[0]
    st.markdown(
        f"<div style='color:{TEXT_DIM}; font-size:11px; margin:4px 0 10px;'>"
        f"共 {len(cmp_tbl)} 个策略 · 按累计收益降序 · 数据源 report/runs/ 运行归档 · "
        f"收益最佳: <b style='color:{ACCENT}'>{best['策略']}</b>（{best['累计收益']:+.2%}）</div>",
        unsafe_allow_html=True)

# ── 收益-回撤散点（多策略定位图）──
sc1, sc2 = st.columns([1.4, 1])
with sc1:
    st.markdown('<div class="panel-title">RETURN vs DRAWDOWN / 收益-回撤定位</div>',
                unsafe_allow_html=True)
    fig = go.Figure()
    for strat in order:
        if strat not in all_runs:
            continue
        r = all_runs[strat]
        fig.add_trace(go.Scatter(
            x=[abs(r["max_drawdown"] or 0)], y=[r["total_return"] or 0],
            mode="markers+text",
            name=r["name"],
            marker=dict(size=16, color=KIND_COLOR.get(r["kind"], ACCENT)),
            text=[f"{r['name']}"], textposition="top center",
            hovertemplate=(f"{r['name']}<br>回撤 %{{x:.2%}}<br>收益 %{{y:.2%}}"
                           "<extra></extra>"),
        ))
    fig.update_layout(
        margin=dict(l=10, r=10, t=30, b=10), height=360,
        xaxis=dict(title="最大回撤(绝对值)", tickformat=".0%"),
        yaxis=dict(title="累计收益", tickformat=".0%"),
    )
    fig.update_xaxes(showgrid=True, gridcolor=BORDER)
    fig.update_yaxes(showgrid=True, gridcolor=BORDER)
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
with sc2:
    st.markdown('<div class="panel-title">LEGEND / 类型图例</div>', unsafe_allow_html=True)
    legend_rows = "".join(
        f"<tr><td><span style='color:{KIND_COLOR.get(kind, ACCENT)}'>●</span> {kind}</td></tr>"
        for kind in ["对冲", "对冲基准", "非对冲"]
    )
    st.markdown(f"""
    <table class="data-table"><tbody>{legend_rows}</tbody></table>
    <div style="color:{TEXT_DIM}; font-size:11px; margin-top:8px;">
        对冲 = 股票+黄金+纳指三资产配置<br>
        非对冲 = 单一资产暴露（纯股票 / 纯ETF）<br>
        对冲贡献 = 对冲策略 − 纯股票策略（差分）
    </div>
    """, unsafe_allow_html=True)

# ── 多策略净值曲线叠加（归一化）──
st.markdown('<div class="panel-title">MULTI-STRATEGY EQUITY / 多策略净值叠加（归一化）</div>',
            unsafe_allow_html=True)


@st.cache_data(ttl=60)
def load_strategy_equities(strats: list) -> dict:
    """读各策略最新归档的净值曲线（归一化到 1）。"""
    out = {}
    for strat in strats:
        rec = all_runs.get(strat)
        if not rec:
            continue
        eq_file = ROOT / "report" / "runs" / rec["_dir"] / "equity.csv"
        if not eq_file.exists():
            continue
        try:
            s = pd.read_csv(eq_file, parse_dates=["date"]).set_index("date")["equity"]
            if len(s) > 1:
                out[strat] = s / s.iloc[0]
        except Exception:  # noqa: BLE001
            continue
    return out


strat_eqs = load_strategy_equities([s for s in order if s in all_runs])
if strat_eqs:
    fig = go.Figure()
    palette = [ACCENT, "#f59e0b", "#22d3ee", GOLD, "#a78bfa"]
    for i, (strat, eq) in enumerate(strat_eqs.items()):
        r = all_runs[strat]
        fig.add_trace(go.Scatter(
            x=eq.index, y=eq.values, name=r["name"],
            line=dict(color=palette[i % len(palette)], width=1.8),
            hovertemplate="%{x|%Y-%m-%d}<br>净值 %{y:.3f}<extra></extra>",
        ))
    fig.update_layout(
        margin=dict(l=10, r=10, t=30, b=10), height=420,
        hovermode="x unified", dragmode="pan",
        legend=dict(orientation="h", y=1.08, font=dict(size=11)),
    )
    fig.update_xaxes(showgrid=True, gridcolor=BORDER)
    fig.update_yaxes(showgrid=True, gridcolor=BORDER)
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
else:
    st.info("暂无多策略净值曲线归档。")

st.divider()

# ── λ 三档对比（读 report/runs/ 真实运行归档）──
st.markdown('<div class="panel-title">λ RISK DIALS / 风险档位对比（真实运行归档）</div>',
            unsafe_allow_html=True)


@st.cache_data(ttl=60)
def load_lambda_runs() -> dict:
    """从 report/runs/ 读 cross_asset 运行归档，按 λ 取每个档位最新一次。"""
    import json

    runs_dir = ROOT / "report" / "runs"
    if not runs_dir.exists():
        return {}
    by_lam: dict = {}
    for run_dir in sorted(runs_dir.iterdir()):
        meta_file = run_dir / "run.json"
        if not meta_file.is_dir() and not meta_file.exists():
            continue
        try:
            meta = json.loads(meta_file.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        if meta.get("strategy") != "cross_asset" or meta.get("lam") is None:
            continue
        lam = meta["lam"]
        # 同档位取最新（目录名含时间戳，字典序即时间序）
        if lam not in by_lam or run_dir.name > by_lam[lam]["_dir"]:
            by_lam[lam] = {
                "_dir": run_dir.name, "total_return": meta.get("total_return"),
                "max_drawdown": meta.get("max_drawdown"), "sharpe": meta.get("sharpe"),
                "trades": meta.get("n_trades"), "n_assets": meta.get("n_assets"),
                "annual_return": meta.get("annual_return"),
            }
    return {k: v for k, v in sorted(by_lam.items())}


lam_results = load_lambda_runs()
if not lam_results:
    st.info("暂无 λ 三档运行归档（report/runs/）。运行 backtest 后自动生成。")
else:
    lc1, lc2 = st.columns([1, 1.4])
    with lc1:
        st.plotly_chart(lambda_comparison(lam_results), use_container_width=True,
                        config={"displayModeBar": False})
    with lc2:
        rows = "".join(
            f"<tr><td>λ={k}</td>"
            f"<td class='{'up' if v['total_return'] >= 0 else 'down'}'>{v['total_return']:+.2%}</td>"
            f"<td class='down'>{v['max_drawdown']:.2%}</td>"
            f"<td>{v['sharpe']:.3f}</td><td>{v['trades']}</td></tr>"
            for k, v in lam_results.items()
        )
        n_assets = next(iter(lam_results.values())).get("n_assets", "?")
        st.markdown(f"""
        <table class="data-table">
            <thead><tr><th>档位</th><th>累计收益</th><th>最大回撤</th><th>夏普</th><th>成交</th></tr></thead>
            <tbody>{rows}</tbody>
        </table>
        <div style="color:{TEXT_DIM}; font-size:11px; margin-top:6px;">
            同一底层数据/因子/信号，仅 λ 切换 · 全池 {n_assets} 只 · 2015-01 ~ 2026-11 ·
            数据源 report/runs/ 运行归档</div>
        """, unsafe_allow_html=True)

st.divider()

# ── 资产 K 线浏览 ──
st.markdown('<div class="panel-title">ASSET CANDLES / 资产K线</div>', unsafe_allow_html=True)
bars_dir = ROOT / "data" / "bars"
etf_options = {"518880 黄金ETF": "518880", "513100 纳指ETF": "513100"}
sel = st.selectbox("选择标的", list(etf_options.keys()))
code = etf_options[sel]
pf = bars_dir / f"{code}.parquet"
if pf.exists():
    df = pd.read_parquet(pf)
    n = st.slider("最近 N 根", 60, 500, 250)
    st.plotly_chart(candlestick(df.tail(n), title=f"{sel} · {code}"),
                    use_container_width=True, config={"displayModeBar": False})
else:
    st.info(f"未找到 {code} 行情数据。")
