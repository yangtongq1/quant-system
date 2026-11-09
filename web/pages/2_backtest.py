"""回测报告页（终端风格重做：交互图表 + λ 对比 + K线浏览）"""
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from web.theme import ACCENT, TEXT_DIM, inject_css, kpi_card, kpi_grid

st.set_page_config(page_title="回测报告 · QUANT TERMINAL", layout="wide")
st.markdown(inject_css(), unsafe_allow_html=True)

from web.charts import (candlestick, drawdown_chart, equity_chart,
                        lambda_comparison, monthly_heatmap)

st.markdown(f"""
<div style="font-size:22px; font-weight:800; letter-spacing:.04em;
             font-family:'JetBrains Mono',Consolas,monospace; color:{ACCENT};">
    ◈ BACKTEST REPORT
</div>
<div style="color:{TEXT_DIM}; font-size:12px; margin-bottom:10px;">净值 · 回撤 · 月度热力 · λ 三档对比 · 资产K线</div>
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
    st.stop()

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
