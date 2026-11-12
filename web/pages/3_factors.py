"""因子质检页（终端风格重做：IC 条形 + 相关热力）"""
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from web.theme import ACCENT, TEXT_DIM, inject_css
from web.i18n import lang_selector, t

st.set_page_config(page_title="因子质检 · QUANT TERMINAL", layout="wide")
lang_selector()
st.markdown(inject_css(), unsafe_allow_html=True)

from factors.engine import list_factors
from web.charts import factor_corr_heatmap, factor_ic_bar

st.markdown(f"""
<div class="page-title">◈ {t("因子质检")} / FACTOR QA</div>
<div style="color:{TEXT_DIM}; font-size:12px; margin-bottom:10px;">
    IC / ICIR / 覆盖率 / 分年稳定性 / 去相关 · 已注册 {len(list_factors())} 因子
</div>
""", unsafe_allow_html=True)

qa_dir = ROOT / "report" / "qa"
qa_file = qa_dir / "qa_summary.csv"
if not qa_file.exists():
    st.info("暂无质检报告。运行 python main.py factors-qa 生成。")
    st.stop()

qa = pd.read_csv(qa_file)

# IC 条形图
c1, c2 = st.columns([1.1, 1])
with c1:
    st.markdown('<div class="panel-title">IC MEAN / 因子 IC（红正绿负 · 金线=入库阈值）</div>',
                unsafe_allow_html=True)
    st.plotly_chart(factor_ic_bar(qa), use_container_width=True,
                    config={"displayModeBar": False})
with c2:
    st.markdown('<div class="panel-title">REGISTRY / 质检明细</div>', unsafe_allow_html=True)
    rows = ""
    for _, r in qa.iterrows():
        ic = float(r["ic_mean"])
        cls = "up" if ic >= 0 else "down"
        alert = " ⚠" if str(r.get("corr_alerts", "[]")) not in ("[]", "nan", "") else ""
        rows += (
            f"<tr><td>{r['factor']}{alert}</td>"
            f"<td class='{cls}'>{ic:+.4f}</td>"
            f"<td>{float(r['icir']):+.3f}</td>"
            f"<td>{float(r['coverage']):.1%}</td></tr>"
        )
    st.markdown(f"""
    <table class="data-table">
        <thead><tr><th>因子</th><th>IC均值</th><th>ICIR</th><th>覆盖率</th></tr></thead>
        <tbody>{rows}</tbody>
    </table>
    <div style="color:{TEXT_DIM}; font-size:11px; margin-top:6px;">⚠ = 与存量因子相关性 &gt; 0.6 告警</div>
    """, unsafe_allow_html=True)

# 因子间相关矩阵（从 corr_alerts 提取或现算）
st.markdown('<div class="panel-title">CROSS CORRELATION / 因子相关矩阵</div>', unsafe_allow_html=True)
try:
    from factors.engine import FactorEngine
    import numpy as np

    # 用黄金+纳指+若干代表股票的近一年数据现算因子截面相关
    codes = ["518880", "513100"]
    bars = {}
    for c in codes:
        p = ROOT / "data" / "bars" / f"{c}.parquet"
        if p.exists():
            bars[c] = pd.read_parquet(p).tail(500)

    engine = FactorEngine()
    frames = {}
    for c, df in bars.items():
        try:
            fvals = engine.compute(df)
            fvals.index = pd.to_datetime(df["date"].values)
            frames[c] = fvals
        except Exception:  # noqa: BLE001
            continue
    combined = pd.concat(frames.values())
    corr = combined.corr()
    st.plotly_chart(factor_corr_heatmap(corr), use_container_width=True,
                    config={"displayModeBar": False})
except Exception as e:  # noqa: BLE001
    st.info(f"相关矩阵暂不可用：{e}")

st.divider()
st.caption("质检标准：|IC均值| > 0.03 且 ICIR > 0.5 且分层单调；与存量因子相关性 > 0.6 告警。")
