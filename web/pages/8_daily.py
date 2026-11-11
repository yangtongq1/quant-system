"""交易日报页（看板展示 report/daily/*.md + 一键生成当日/补生成历史）。"""
import sys
from datetime import datetime, timedelta
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from web.i18n import t
from web.theme import TEXT_DIM, inject_css

st.set_page_config(page_title="交易日报 · QUANT TERMINAL", layout="wide")
st.markdown(inject_css(), unsafe_allow_html=True)

st.markdown(f"""
<div class="page-title">◈ {t("交易日报")} / DAILY REPORT</div>
<div style="color:{TEXT_DIM}; font-size:12px; margin-bottom:10px;">
    当日成交 · 持仓快照 · 数据健康 · 自动生成</div>
""", unsafe_allow_html=True)

daily_dir = ROOT / "report" / "daily"
existing = sorted(daily_dir.glob("*.md"), reverse=True) if daily_dir.exists() else []

c1, c2 = st.columns([3, 1])
with c1:
    if existing:
        dates = [p.stem for p in existing]
        pick = st.selectbox(t("日期"), dates, index=0, label_visibility="collapsed")
    else:
        pick = None
        st.info(t("暂无数据") + "。点击右侧生成。")
with c2:
    if st.button(f"⚡ {t('生成日报')}（今天）", use_container_width=True):
        with st.spinner(t("运行中…")):
            try:
                sys.path.insert(0, str(ROOT / "scripts"))
                from daily_report import generate
                p = generate()
                st.success(f"{t('报告已生成')}：{p.name}")
                st.cache_data.clear()
                st.rerun()
            except Exception as e:  # noqa: BLE001
                st.error(f"生成失败：{e}")

if pick:
    content = (daily_dir / f"{pick}.md").read_text(encoding="utf-8")
    st.markdown(content)
    st.divider()
    # 昨日/今日快捷补生成
    back = st.columns(5)
    for i, btn in enumerate(back):
        d = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
        if i == 0:
            continue
        if btn.button(f"补生成 {d[5:]}", key=f"gen_{d}", use_container_width=True):
            try:
                sys.path.insert(0, str(ROOT / "scripts"))
                from daily_report import generate
                generate(d)
                st.success(f"{d} {t('报告已生成')}")
                st.cache_data.clear()
                st.rerun()
            except Exception as e:  # noqa: BLE001
                st.error(f"{d} 生成失败：{e}")
