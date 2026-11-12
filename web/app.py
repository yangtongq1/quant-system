"""Web 看板主入口（M7 · Bloomberg 终端风格重做版）

启动：streamlit run web/app.py → http://127.0.0.1:8765

侧栏导航：st.navigation() 接管（页面标题走 i18n，中英切换全局生效）。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from web.i18n import t
from web.theme import (ACCENT, GOLD, NASDAQ, UP, DOWN, TEXT_DIM, inject_css,
                       kpi_card, kpi_grid)

st.set_page_config(page_title="QUANT TERMINAL · 金融工作台",
                   page_icon="◉", layout="wide")

# ── 侧栏导航（st.navigation 接管：页面顺序 + i18n 标题） ──
_PAGES: list[tuple[str, str]] = [
    ("0_console", "系统控制台"),
    ("1_positions", "持仓与订单"),
    ("2_backtest", "回测报告"),
    ("3_factors", "因子质检"),
    ("4_risk", "风控中心"),
    ("5_knowledge", "知识库"),
    ("6_runs", "运行中心"),
    ("7_settlement", "交割单"),
    ("8_daily", "交易日报"),
    ("9_oneclick", "一键操作台"),
    ("10_market", "行情与舆情"),
    ("11_analysis", "绩效分析"),
    ("12_stock_view", "个股K线"),
]

_icons = {
    "0_console": "🛠", "1_positions": "◎", "2_backtest": "📋", "3_factors": "🧪",
    "4_risk": "🛡", "5_knowledge": "📚", "6_runs": "⚙", "7_settlement": "🧾",
    "8_daily": "📰", "9_oneclick": "⚡", "10_market": "📈", "11_analysis": "📊",
    "12_stock_view": "🕯",
}


def build_nav() -> None:
    """构建侧栏导航（语言切换时整体重建）。"""
    # st.Page 相对主脚本目录解析 → 用绝对路径（基于 ROOT）
    pages = [
        st.Page(str(ROOT / "web" / "home.py"), title=f"🏠 {t('首页仪表盘')}", icon=None),
    ]
    pages += [
        st.Page(
            str(ROOT / "web" / "pages" / f"{fname}.py"),
            title=f"{_icons[fname]} {t(title)}",
            icon=None,
        )
        for fname, title in _PAGES
    ]
    pg = st.navigation(pages, position="sidebar", expanded=False)
    # 侧栏顶部：品牌 + 语言切换（i18n.lang_selector 渲染在 sidebar）
    from web.i18n import lang_selector
    with st.sidebar:
        st.markdown(
            f'<div style="font-size:15px; font-weight:800; letter-spacing:.05em; '
            f'font-family:JetBrains Mono,Consolas,monospace; color:{ACCENT}; '
            f'padding:2px 0 6px 0;">◉ QUANT TERMINAL</div>'
            f'<div style="font-size:11px; color:{TEXT_DIM}; '
            f'padding-bottom:8px;">{t("跨资产对冲配置")}</div>',
            unsafe_allow_html=True)
        lang_selector("sidebar")
    pg.run()


build_nav()
