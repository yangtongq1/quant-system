"""运行中心页：所有回测运行归档（report/runs/）——数据跑过的痕迹都在这"""
import json
import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from web.theme import ACCENT, TEXT_DIM, inject_css

st.set_page_config(page_title="运行中心 · QUANT TERMINAL", layout="wide")
st.markdown(inject_css(), unsafe_allow_html=True)

st.markdown(f"""
<div class="page-title">◈ RUN CENTER</div>
<div style="color:{TEXT_DIM}; font-size:12px; margin-bottom:10px;">
    回测运行归档 · 每次运行自动留痕（参数/指标/净值）· 目录 report/runs/</div>
""", unsafe_allow_html=True)


@st.cache_data(ttl=30)
def load_runs() -> list[dict]:
    runs_dir = ROOT / "report" / "runs"
    if not runs_dir.exists():
        return []
    out = []
    for run_dir in sorted(runs_dir.iterdir(), reverse=True):
        meta_file = run_dir / "run.json"
        if not meta_file.exists():
            continue
        try:
            meta = json.loads(meta_file.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        meta["_dir"] = run_dir.name
        meta["_has_equity"] = (run_dir / "equity.csv").exists()
        out.append(meta)
    return out


runs = load_runs()
if not runs:
    st.info("暂无运行归档。运行 python main.py backtest ... 后自动留痕到 report/runs/。")
    st.stop()


def fmt_pct(v):
    return f"{v:+.2%}" if isinstance(v, (int, float)) else "-"


def fmt_num(v, nd=3):
    return f"{v:.{nd}f}" if isinstance(v, (int, float)) else "-"


rows = "".join(
    f"<tr><td>{r.get('timestamp', '-')}</td>"
    f"<td>{r.get('strategy', '-')}</td>"
    f"<td>{'' if r.get('lam') is None else 'λ=' + str(r.get('lam'))}</td>"
    f"<td>{r.get('n_assets', '-')}</td>"
    f"<td>{'' if r.get('top_n') is None else r.get('top_n')}</td>"
    f"<td class='{'up' if (r.get('total_return') or 0) >= 0 else 'down'}'>{fmt_pct(r.get('total_return'))}</td>"
    f"<td>{fmt_pct(r.get('annual_return'))}</td>"
    f"<td class='down'>{fmt_pct(r.get('max_drawdown'))}</td>"
    f"<td>{fmt_num(r.get('sharpe'))}</td>"
    f"<td>{r.get('n_trades', '-')}</td>"
    f"<td>{'✓' if r.get('_has_equity') else '—'}</td></tr>"
    for r in runs
)

st.markdown(f"""
<table class="data-table">
    <thead><tr><th>时间</th><th>策略</th><th>λ</th><th>池</th><th>TopN</th>
    <th>累计收益</th><th>年化</th><th>最大回撤</th><th>夏普</th><th>成交</th><th>曲线</th></tr></thead>
    <tbody>{rows}</tbody>
</table>
<div style="color:{TEXT_DIM}; font-size:11px; margin-top:8px;">
    共 {len(runs)} 次运行 · 归档目录 report/runs/ · 含 run.json（参数+指标）与 equity.csv（净值曲线）</div>
""", unsafe_allow_html=True)

st.divider()
sel = st.selectbox("查看净值曲线", [r["_dir"] for r in runs], index=0)
eq_file = ROOT / "report" / "runs" / sel / "equity.csv"
if eq_file.exists():
    import pandas as pd
    from web.charts import drawdown_chart, equity_chart

    eq = pd.read_csv(eq_file, parse_dates=["date"]).set_index("date")["equity"]
    c1, c2 = st.columns([2.2, 1])
    with c1:
        st.markdown('<div class="panel-title">EQUITY / 净值</div>', unsafe_allow_html=True)
        st.plotly_chart(equity_chart(eq, initial=float(eq.iloc[0])),
                        use_container_width=True, config={"displayModeBar": False})
    with c2:
        st.markdown('<div class="panel-title">DRAWDOWN / 水下</div>', unsafe_allow_html=True)
        st.plotly_chart(drawdown_chart(eq), use_container_width=True,
                        config={"displayModeBar": False})
else:
    st.info(f"该运行无净值曲线文件（{sel}，补录归档仅指标）。")

st.divider()
st.markdown(f"""
<div style="color:{TEXT_DIM}; font-size:12px;">
    运行明细 JSON：</div>
""", unsafe_allow_html=True)
meta_file = ROOT / "report" / "runs" / sel / "run.json"
if meta_file.exists():
    st.code(meta_file.read_text(encoding="utf-8"), language="json")
