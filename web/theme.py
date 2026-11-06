"""Bloomberg 终端风格深色主题 + Plotly 模板（M7 UI 重做）

设计参考（外网调研结论）：
- Bloomberg Terminal / QUANT_CORE：#0A0D14 深底 + IBM Plex Mono 等宽数据字体 + 高亮青绿
- 专业量化终端要素：KPI 卡片网格、live 状态呼吸灯、plotly_dark、涨红跌绿（A股惯例）
"""

from __future__ import annotations

import plotly.graph_objects as go
import plotly.io as pio

# ── 调色板（终端风）────────────────────────────────────────────
BG = "#0A0E17"          # 主背景（近黑深蓝）
PANEL = "#111827"       # 卡片/面板
PANEL_2 = "#0D1320"     # 次级面板
BORDER = "#1E293B"      # 边框
TEXT = "#E2E8F0"        # 主文字
TEXT_DIM = "#94A3B8"    # 次要文字
ACCENT = "#22D3EE"      # 青色强调（终端经典）
ACCENT_2 = "#A78BFA"     # 紫色辅助
UP = "#F87171"          # 涨（A股：红涨）
DOWN = "#4ADE80"        # 跌（A股：绿跌）
GOLD = "#FBBF24"        # 黄金资产色
NASDAQ = "#60A5FA"      # 纳指资产色

FONT_MONO = "'JetBrains Mono','IBM Plex Mono','Cascadia Code',Consolas,monospace"
FONT_BODY = "'Inter','Segoe UI','PingFang SC','Microsoft YaHei',sans-serif"

# ── Streamlit 全局 CSS（覆盖默认皮肤）──────────────────────────
def inject_css() -> str:
    """返回注入 <style> 的 CSS 文本（st.markdown(unsafe_allow_html=True) 用）。"""
    return f"""
<style>
/* ══════════ 全局 ══════════ */
.stApp {{
    background: {BG};
    color: {TEXT};
    font-family: {FONT_BODY};
}}
#MainMenu, footer, header[data-testid="stHeader"] {{
    visibility: hidden;
    height: 0;
}}
section[data-testid="stSidebar"] {{
    background: {PANEL_2};
    border-right: 1px solid {BORDER};
}}
section[data-testid="stSidebar"] * {{
    color: {TEXT} !important;
}}
h1, h2, h3, h4 {{
    color: {TEXT} !important;
    font-weight: 700;
    letter-spacing: 0.02em;
}}
p, span, label, caption {{
    color: {TEXT} !important;
}}
.stCaption, p > small {{
    color: {TEXT_DIM} !important;
}}

/* ══════════ KPI 卡片 ══════════ */
.kpi-grid {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
    gap: 14px;
    margin: 8px 0 18px 0;
}}
.kpi-card {{
    background: linear-gradient(145deg, {PANEL} 0%, {PANEL_2} 100%);
    border: 1px solid {BORDER};
    border-radius: 12px;
    padding: 16px 18px;
    position: relative;
    overflow: hidden;
    transition: transform .25s ease, border-color .25s ease, box-shadow .25s ease;
}}
.kpi-card:hover {{
    transform: translateY(-3px);
    border-color: {ACCENT};
    box-shadow: 0 8px 28px rgba(34,211,238,.18);
}}
.kpi-card::before {{
    content: '';
    position: absolute;
    top: 0; left: 0; right: 0;
    height: 2px;
    background: linear-gradient(90deg, {ACCENT}, transparent 70%);
    opacity: 0;
    transition: opacity .3s;
}}
.kpi-card:hover::before {{ opacity: 1; }}
.kpi-label {{
    font-size: 12px;
    color: {TEXT_DIM};
    letter-spacing: .12em;
    text-transform: uppercase;
    margin-bottom: 6px;
}}
.kpi-value {{
    font-family: {FONT_MONO};
    font-size: 26px;
    font-weight: 700;
    color: {TEXT};
}}
.kpi-sub {{
    font-size: 12px;
    color: {TEXT_DIM};
    margin-top: 4px;
}}
.kpi-up {{ color: {UP} !important; }}
.kpi-down {{ color: {DOWN} !important; }}
.kpi-gold {{ color: {GOLD} !important; }}
.kpi-nasdaq {{ color: {NASDAQ} !important; }}

/* ══════════ 状态呼吸灯 ══════════ */
.live-dot {{
    display: inline-block;
    width: 9px; height: 9px;
    border-radius: 50%;
    background: {UP};
    margin-right: 8px;
    box-shadow: 0 0 0 0 rgba(248,113,113,.7);
    animation: pulse 2s infinite;
}}
@keyframes pulse {{
    0%   {{ box-shadow: 0 0 0 0 rgba(248,113,113,.6); }}
    70%  {{ box-shadow: 0 0 0 10px rgba(248,113,113,0); }}
    100% {{ box-shadow: 0 0 0 0 rgba(248,113,113,0); }}
}}
.live-dot.cyan {{ background: {ACCENT}; }}
.live-dot.cyan {{ animation-name: pulse-cyan; }}
@keyframes pulse-cyan {{
    0%   {{ box-shadow: 0 0 0 0 rgba(34,211,238,.6); }}
    70%  {{ box-shadow: 0 0 0 10px rgba(34,211,238,0); }}
    00%  {{ box-shadow: 0 0 0 0 rgba(34,211,238,0); }}
}}
.live-dot.green {{ background: #22C55E; animation-name: pulse-green; }}
@keyframes pulse-green {{
    0%   {{ box-shadow: 0 0 0 0 rgba(34,197,94,.6); }}
    70%  {{ box-shadow: 0 0 0 10px rgba(34,197,94,0); }}
    100% {{ box-shadow: 0 0 0 0 rgba(34,197,94,0); }}
}}

/* ══════════ 面板 ══════════ */
.panel {{
    background: {PANEL_2};
    border: 1px solid {BORDER};
    border-radius: 12px;
    padding: 18px 20px;
    margin: 10px 0;
}}
.panel-title {{
    font-size: 13px;
    color: {ACCENT};
    letter-spacing: .15em;
    text-transform: uppercase;
    font-weight: 700;
    margin-bottom: 12px;
    font-family: {FONT_MONO};
}}
.mono {{ font-family: {FONT_MONO}; }}

/* ══════════ 表格 ══════════ */
.data-table {{
    width: 100%;
    border-collapse: collapse;
    font-family: {FONT_MONO};
    font-size: 13px;
}}
.data-table th {{
    background: {PANEL};
    color: {ACCENT};
    text-align: left;
    padding: 9px 12px;
    border-bottom: 2px solid {BORDER};
    letter-spacing: .06em;
    font-size: 12px;
}}
.data-table td {{
    padding: 8px 12px;
    border-bottom: 1px solid {BORDER};
    color: {TEXT};
}}
.data-table tr:hover td {{
    background: rgba(34,211,238,.06);
}}
td.up {{ color: {UP} !important; }}
td.down {{ color: {DOWN} !important; }}

/* ══════════ 排行/条形装饰 ══════════ */
.bar-track {{
    background: {PANEL};
    border-radius: 4px;
    height: 8px;
    width: 100%;
    overflow: hidden;
}}
.bar-fill {{
    height: 100%;
    border-radius: 4px;
    background: linear-gradient(90deg, {ACCENT}, {ACCENT_2});
    transition: width .8s cubic-bezier(.22,1,.36,1);
}}

/* ══════════ Streamlit 组件深色化 ══════════ */
.stTabs [data-baseweb="tab"] {{
    background-color: transparent;
    color: {TEXT_DIM};
    border-radius: 8px 8px 0 0;
    font-family: {FONT_MONO};
}}
.stTabs [aria-selected="true"] {{
    background-color: {PANEL} !important;
    color: {ACCENT} !important;
    border-bottom: 2px solid {ACCENT} !important;
}}
div[data-testid="stDataFrame"] {{
    border: 1px solid {BORDER};
    border-radius: 10px;
}}
.stButton > button {{
    background: {PANEL};
    color: {ACCENT};
    border: 1px solid {BORDER};
    border-radius: 8px;
    font-family: {FONT_MONO};
    transition: all .2s;
}}
.stButton > button:hover {{
    border-color: {ACCENT};
    box-shadow: 0 0 14px rgba(34,211,238,.25);
}}
div[data-testid="stMetric"] {{
    background: {PANEL_2};
    border: 1px solid {BORDER};
    border-radius: 10px;
    padding: 12px 14px;
}}
div[data-testid="stMetricValue"] {{
    font-family: {FONT_MONO};
}}

/* 页面淡入 */
.main .block-container {{
    animation: fadeIn .45s ease;
    padding-top: 1.6rem;
    max-width: 1400px;
}}
@keyframes fadeIn {{
    from {{ opacity: 0; transform: translateY(8px); }}
    to   {{ opacity: 1; transform: translateY(0); }}
}}

/* 滚动条 */
::-webkit-scrollbar {{ width: 9px; height: 9px; }}
::-webkit-scrollbar-track {{ background: {PANEL_2}; }}
::-webkit-scrollbar-thumb {{ background: {BORDER}; border-radius: 5px; }}
::-webkit-scrollbar-thumb:hover {{ background: {ACCENT}; }}
</style>
"""


def kpi_card(label: str, value: str, sub: str = "", cls: str = "") -> str:
    """KPI 卡片 HTML。cls: kpi-up / kpi-down / kpi-gold / kpi-nasdaq"""
    return f"""
<div class="kpi-card">
    <div class="kpi-label">{label}</div>
    <div class="kpi-value {cls}">{value}</div>
    {f'<div class="kpi-sub">{sub}</div>' if sub else ''}
</div>"""


def kpi_grid(cards: list[str]) -> str:
    return f'<div class="kpi-grid">{"".join(cards)}</div>'


# ── Plotly 深色模板 ────────────────────────────────────────────
def _build_template() -> go.layout.Template:
    layout = go.Layout(
        paper_bgcolor=BG,
        plot_bgcolor=BG,
        font=dict(family="JetBrains Mono, IBM Plex Mono, Consolas, monospace",
                  size=12, color=TEXT),
        colorway=[ACCENT, ACCENT_2, GOLD, NASDAQ, UP, DOWN],
        xaxis=dict(gridcolor=BORDER, zerolinecolor=BORDER),
        yaxis=dict(gridcolor=BORDER, zerolinecolor=BORDER),
        hoverlabel=dict(bgcolor=PANEL, bordercolor=ACCENT,
                         font=dict(color=TEXT, family="JetBrains Mono")),
        legend=dict(bgcolor="rgba(0,0,0,0)", font=dict(color=TEXT_DIM)),
        title=dict(font=dict(color=TEXT, size=14)),
    )
    return go.layout.Template(layout=layout)


def apply_theme():
    """注册并启用终端主题模板。"""
    pio.templates["terminal"] = _build_template()
    pio.templates.default = "terminal"


apply_theme()
