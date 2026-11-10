"""Bloomberg 终端风格深色主题 + Plotly 模板（M7 UI 重做 → 2026-11 高端特效升级版）

设计参考（外网调研结论）：
- Bloomberg Terminal / QUANT_CORE：#0A0D14 深底 + IBM Plex Mono 等宽数据字体 + 高亮青绿
- SolanaTradeBot FUTURISTIC_UI_GUIDE：玻璃拟态 + 辉光边框 + 悬浮抬升 + 流光扫过
- Glassmorphism Shimmer（quackit）：skewX(-20deg) 半透明白光扫过卡片
- Finova / Aegis Prime：渐变大数字 + 环境径向辉光 + 呼吸状态灯
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
/* ══════════ 全局（环境径向辉光背景）══════════ */
.stApp {{
    background:
        radial-gradient(ellipse 60% 40% at 12% 0%, rgba(34,211,238,.07), transparent 60%),
        radial-gradient(ellipse 50% 35% at 88% 8%, rgba(167,139,250,.06), transparent 60%),
        radial-gradient(ellipse 70% 50% at 50% 110%, rgba(34,211,238,.04), transparent 65%),
        {BG};
    color: {TEXT};
    font-family: {FONT_BODY};
}}
#MainMenu, footer {{
    visibility: hidden;
    height: 0;
}}
/* 保留 stHeader（侧边栏折叠后的唯一展开入口在里面），只做透明化融入暗色主题；
   隐藏 header 会连「Expand sidebar」按钮一起藏掉 → 侧边栏收起后无法恢复 */
header[data-testid="stHeader"] {{
    background: transparent;
    border: none;
}}
header[data-testid="stHeader"] button[aria-label="Main menu"],
header[data-testid="stHeader"] button[aria-label="Running"] {{
    visibility: hidden;
}}
section[data-testid="stSidebar"] {{
    background: {PANEL_2};
    border-right: 1px solid {BORDER};
}}
section[data-testid="stSidebar"] * {{
    color: {TEXT} !important;
}}
/* 侧边栏展开/收起按钮：终端风格高亮，确保任何窗口宽度下可见可点 */
header[data-testid="stHeader"] button[aria-label="Expand sidebar"],
header[data-testid="stHeader"] button[aria-label="Collapse sidebar"] {{
    visibility: visible !important;
    color: {ACCENT} !important;
    background: {PANEL} !important;
    border: 1px solid {BORDER} !important;
    border-radius: 8px !important;
    min-width: 34px;
    min-height: 34px;
    z-index: 999;
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

/* ══════════ KPI 卡片（玻璃拟态 + 流光特效）══════════ */
.kpi-grid {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
    gap: 14px;
    margin: 8px 0 18px 0;
}}
.kpi-card {{
    background: linear-gradient(145deg, rgba(17,24,39,.92) 0%, rgba(13,19,32,.95) 100%);
    backdrop-filter: blur(14px);
    -webkit-backdrop-filter: blur(14px);
    border: 1px solid rgba(34,211,238,.14);
    border-radius: 14px;
    padding: 16px 18px;
    position: relative;
    overflow: hidden;
    transition: transform .3s cubic-bezier(.4,0,.2,1), border-color .3s ease,
                box-shadow .3s ease, background .3s ease;
    box-shadow: 0 4px 20px rgba(0,0,0,.35);
}}
.kpi-card:hover {{
    transform: translateY(-5px) scale(1.015);
    border-color: rgba(34,211,238,.55);
    box-shadow: 0 12px 36px rgba(34,211,238,.22), 0 0 0 1px rgba(34,211,238,.15);
    background: linear-gradient(145deg, rgba(23,33,54,.95) 0%, rgba(15,23,40,.96) 100%);
}}
/* 顶部渐变光带（常显微光，悬停增强） */
.kpi-card::before {{
    content: '';
    position: absolute;
    top: 0; left: 0; right: 0;
    height: 2px;
    background: linear-gradient(90deg, transparent, {ACCENT}, {ACCENT_2}, transparent);
    background-size: 200% 100%;
    opacity: .45;
    transition: opacity .3s;
    animation: borderflow 3.5s linear infinite;
}}
.kpi-card:hover::before {{ opacity: 1; }}
/* 流光扫过特效（skewX 斜光带从左划到右，循环） */
.kpi-card::after {{
    content: '';
    position: absolute;
    top: -60%;
    left: -80%;
    width: 45%;
    height: 220%;
    background: linear-gradient(115deg, transparent 25%, rgba(148,233,255,.13) 48%,
                rgba(167,139,250,.10) 55%, transparent 75%);
    transform: skewX(-20deg);
    animation: shimmer 4.5s ease-in-out infinite;
    pointer-events: none;
}}
@keyframes shimmer {{
    0%   {{ left: -80%; }}
    55%  {{ left: 130%; }}
    100% {{ left: 130%; }}
}}
@keyframes borderflow {{
    0%   {{ background-position: 0% 50%; }}
    100% {{ background-position: 200% 50%; }}
}}
.kpi-label {{
    font-size: 12px;
    color: {TEXT_DIM};
    letter-spacing: .12em;
    text-transform: uppercase;
    margin-bottom: 6px;
}}
.kpi-value {{
    font-family: {FONT_MONO};
    font-size: 27px;
    font-weight: 800;
    background: linear-gradient(135deg, #F1F5F9 20%, {ACCENT} 75%, {ACCENT_2} 100%);
    background-clip: text;
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    letter-spacing: .01em;
}}
.kpi-up .kpi-value {{
    background: linear-gradient(135deg, #FECACA 20%, {UP} 80%);
    background-clip: text; -webkit-background-clip: text; -webkit-text-fill-color: transparent;
}}
.kpi-down .kpi-value {{
    background: linear-gradient(135deg, #DCFCE7 20%, {DOWN} 80%);
    background-clip: text; -webkit-background-clip: text; -webkit-text-fill-color: transparent;
}}
.kpi-gold .kpi-value {{
    background: linear-gradient(135deg, #FEF3C7 20%, {GOLD} 80%);
    background-clip: text; -webkit-background-clip: text; -webkit-text-fill-color: transparent;
}}
.kpi-nasdaq .kpi-value {{
    background: linear-gradient(135deg, #DBEAFE 20%, {NASDAQ} 80%);
    background-clip: text; -webkit-background-clip: text; -webkit-text-fill-color: transparent;
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

/* ══════════ 面板（玻璃拟态 + 环境辉光）══════════ */
.panel {{
    background: rgba(13,19,32,.82);
    backdrop-filter: blur(12px);
    -webkit-backdrop-filter: blur(12px);
    border: 1px solid rgba(34,211,238,.10);
    border-radius: 14px;
    padding: 18px 20px;
    margin: 10px 0;
    box-shadow: 0 4px 24px rgba(0,0,0,.3), inset 0 1px 0 rgba(255,255,255,.04);
}}
.panel-title {{
    font-size: 13px;
    color: {ACCENT};
    letter-spacing: .15em;
    text-transform: uppercase;
    font-weight: 700;
    margin-bottom: 12px;
    font-family: {FONT_MONO};
    text-shadow: 0 0 18px rgba(34,211,238,.45);
}}
.mono {{ font-family: {FONT_MONO}; }}

/* ══════════ 表格（行悬浮辉光）══════════ */
.data-table {{
    width: 100%;
    border-collapse: collapse;
    font-family: {FONT_MONO};
    font-size: 13px;
}}
.data-table th {{
    background: linear-gradient(180deg, rgba(17,24,39,.95), rgba(13,19,32,.98));
    color: {ACCENT};
    text-align: left;
    padding: 9px 12px;
    border-bottom: 1px solid rgba(34,211,238,.25);
    letter-spacing: .06em;
    font-size: 12px;
    text-shadow: 0 0 12px rgba(34,211,238,.35);
}}
.data-table td {{
    padding: 8px 12px;
    border-bottom: 1px solid rgba(30,41,59,.7);
    color: {TEXT};
    transition: background .18s ease, padding-left .18s ease;
}}
.data-table tr:hover td {{
    background: linear-gradient(90deg, rgba(34,211,238,.10), rgba(34,211,238,.02));
    padding-left: 16px;
}}
td.up {{ color: {UP} !important; text-shadow: 0 0 14px rgba(248,113,113,.35); }}
td.down {{ color: {DOWN} !important; text-shadow: 0 0 14px rgba(74,222,128,.35); }}

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

/* ══════════ 页面主标题流光 ══════════ */
.page-title {{
    font-size: 22px;
    font-weight: 800;
    letter-spacing: .04em;
    font-family: {FONT_MONO};
    background: linear-gradient(90deg, {ACCENT} 0%, #E0F2FE 30%, {ACCENT_2} 60%, {ACCENT} 100%);
    background-size: 250% 100%;
    background-clip: text;
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    animation: titleflow 6s linear infinite;
    display: inline-block;
}}
@keyframes titleflow {{
    0%   {{ background-position: 0% 50%; }}
    100% {{ background-position: 250% 50%; }}
}}

/* Streamlit 按钮升级（悬停抬升 + 辉光） */
.stButton > button {{
    background: linear-gradient(145deg, rgba(17,24,39,.95), rgba(13,19,32,.98));
    color: {ACCENT};
    border: 1px solid rgba(34,211,238,.25);
    border-radius: 9px;
    font-family: {FONT_MONO};
    transition: transform .25s cubic-bezier(.4,0,.2,1), box-shadow .25s, border-color .25s;
    box-shadow: 0 2px 12px rgba(0,0,0,.3);
}}
.stButton > button:hover {{
    transform: translateY(-2px);
    border-color: rgba(34,211,238,.7);
    box-shadow: 0 8px 24px rgba(34,211,238,.28);
    text-shadow: 0 0 12px rgba(34,211,238,.5);
}}
.stButton > button[kind="primary"] {{
    background: linear-gradient(135deg, rgba(34,211,238,.16), rgba(167,139,250,.14));
    border: 1px solid rgba(34,211,238,.5);
}}

/* 滚动条 */
::-webkit-scrollbar {{ width: 9px; height: 9px; }}
::-webkit-scrollbar-track {{ background: {PANEL_2}; }}
::-webkit-scrollbar-thumb {{ background: {BORDER}; border-radius: 5px; }}
::-webkit-scrollbar-thumb:hover {{ background: {ACCENT}; }}

/* ══════════ 无障碍：系统开启「减少动态」时关闭流光动画 ══════════ */
@media (prefers-reduced-motion: reduce) {{
    .kpi-card::before, .kpi-card::after, .page-title {{
        animation: none !important;
    }}
    .kpi-card, .stButton > button, .data-table td {{
        transition: none !important;
    }}
}}
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
