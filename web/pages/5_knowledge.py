"""知识库页（终端风格重做）"""
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from web.theme import ACCENT, ACCENT_2, TEXT_DIM, inject_css

st.set_page_config(page_title="金融知识库 · QUANT TERMINAL", layout="wide")
st.markdown(inject_css(), unsafe_allow_html=True)

from knowledge.storage import KnowledgeStorage

kb = KnowledgeStorage(ROOT / "knowledge" / "knowledge.db")

st.markdown(f"""
<div style="font-size:22px; font-weight:800; letter-spacing:.04em;
             font-family:'JetBrains Mono',Consolas,monospace; color:{ACCENT};">
    ◈ KNOWLEDGE BASE
</div>
<div style="color:{TEXT_DIM}; font-size:12px; margin-bottom:10px;">资讯采集 · 全文检索 · 中英双语</div>
""", unsafe_allow_html=True)

query = st.text_input(
    "全文检索（中英文标题/摘要）",
    placeholder="例如: inflation / 美联储 / 黄金 / interest rate",
)
if query:
    results = kb.search(query, limit=30)
    if results.empty:
        st.info("未检索到相关文章。先运行 python main.py fetch-news 采集。")
    else:
        st.success(f"检索到 {len(results)} 条")
        for i, (_, r) in enumerate(results.iterrows()):
            st.markdown(f"""
            <div class="panel" style="border-left: 3px solid {ACCENT_2 if i % 2 else ACCENT};">
                <div style="font-weight:700; font-size:15px; margin-bottom:2px;">
                    {r.get('title_zh') or r.get('title', '')}
                </div>
                <div style="color:{TEXT_DIM}; font-size:11px; margin-bottom:6px;" class="mono">
                    {r.get('source', '')} ｜ {r.get('category', '')} ｜ {r.get('published', '')}
                </div>
                <div style="font-size:13px; color:#CBD5E1;">
                    {(r.get('summary_zh') or str(r.get('summary', ''))[:200] or '')}
                </div>
                {f"<div style='margin-top:6px;'><a href='{r['link']}' style='color:{ACCENT}; font-size:12px;'>原文链接 →</a></div>" if r.get('link') else ''}
            </div>
            """, unsafe_allow_html=True)
    st.stop()

# ── 浏览最近文章 ──
st.markdown('<div class="panel-title">RECENT / 最近文章</div>', unsafe_allow_html=True)
category = st.selectbox("分类", ["全部", "财经", "宏观"])
cat = None if category == "全部" else category
recent = kb.recent(limit=50, category=cat)
if recent.empty:
    st.info("知识库为空。先运行 python main.py fetch-news 采集资讯。")
else:
    for i, (_, r) in enumerate(recent.iterrows()):
        st.markdown(f"""
        <div class="panel" style="border-left: 3px solid {ACCENT_2 if i % 2 else ACCENT};">
            <div style="font-weight:700; font-size:15px; margin-bottom:2px;">
                {r.get('title_zh') or r.get('title', '')}
            </div>
            <div style="color:{TEXT_DIM}; font-size:11px; margin-bottom:6px;" class="mono">
                {r.get('source', '')} ｜ {r.get('category', '')} ｜ {r.get('published', '')}
            </div>
            <div style="font-size:13px; color:#CBD5E1;">
                {(r.get('summary_zh') or str(r.get('summary', ''))[:200] or '')}
            </div>
            {f"<div style='margin-top:6px;'><a href='{r['link']}' style='color:{ACCENT}; font-size:12px;'>原文链接 →</a></div>" if r.get('link') else ''}
        </div>
        """, unsafe_allow_html=True)
