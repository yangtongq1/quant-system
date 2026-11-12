"""行情与舆情页：实时行情（xtdata）+ 市场快讯（东财）+ 持仓自选。

数据源：
- 实时行情：xtdata（QMT 本地行情，延迟 2-5 秒）——指数 + 持仓股
- 财经快讯：akshare 东财全球快讯（200 条实时）
- 市场情绪：持仓股涨跌统计 + 快讯关键词
"""
import sqlite3
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from web.i18n import lang_selector, t
from web.theme import ACCENT, DOWN, TEXT_DIM, UP, inject_css, kpi_card, kpi_grid

st.set_page_config(page_title="行情与舆情 · QUANT TERMINAL", layout="wide")
lang_selector()
st.markdown(inject_css(), unsafe_allow_html=True)

st.markdown(f"""
<div class="page-title">◈ {t("行情与舆情")} / MARKET & SENTIMENT</div>
<div style="color:{TEXT_DIM}; font-size:12px; margin-bottom:10px;">
    实时行情（QMT） · 财经快讯 · 持仓自选 · 双语</div>
""", unsafe_allow_html=True)

ETF_NAMES = {"518880": "黄金ETF", "513100": "纳指ETF"}


def load_names() -> dict:
    db = ROOT / "data" / "quant.db"
    if not db.exists():
        return {}
    with sqlite3.connect(str(db)) as conn:
        try:
            df = pd.read_sql("SELECT code, name FROM stocks", conn)
            return dict(zip(df["code"].astype(str), df["name"]))
        except Exception:  # noqa: BLE001
            return {}


def load_positions() -> list[str]:
    db = ROOT / "data" / "quant.db"
    if not db.exists():
        return []
    try:
        with sqlite3.connect(str(db)) as conn:
            rows = conn.execute(
                "SELECT code FROM positions WHERE volume > 0").fetchall()
        return [r[0] for r in rows]
    except Exception:  # noqa: BLE001
        return []


def to_sym(code: str) -> str:
    if code.startswith(("6", "9", "5")):
        return f"{code}.SH"
    if code.startswith(("0", "3", "1")):
        return f"{code}.SZ"
    return f"{code}.BJ"


tab_q, tab_n, tab_s = st.tabs([f"📈 {t('指数行情')}",
                               f"📰 {t('快讯')}",
                               f"⭐ {t('自选股行情')}"])

# ── Tab 1: 指数实时行情（xtdata） ──
with tab_q:
    INDEX = {  # xtdata 合约
        "000001.SH": "上证指数", "399001.SZ": "深证成指", "399006.SZ": "创业板指",
        "000300.SH": "沪深300", "000905.SH": "中证500",
    }
    if st.button(f"🔄 {t('刷新')}", key="idx"):
        st.cache_data.clear()
    try:
        @st.cache_data(ttl=15, show_spinner=False)
        def index_quotes() -> pd.DataFrame:
            from xtquant import xtdata
            ticks = xtdata.get_full_tick(list(INDEX))
            rows = []
            for sym, name in INDEX.items():
                d = ticks.get(sym) or {}
                last = d.get("lastPrice", 0)
                # 无昨收时跳过涨跌计算
                rows.append({"指数": name, "最新": last, "数据": bool(d)})
            return pd.DataFrame(rows)
        dfq = index_quotes()
        if dfq.empty or not dfq["数据"].any():
            st.info("xtdata 未连接（QMT 客户端未启动时无实时行情）")
        else:
            st.dataframe(dfq[["指数", "最新"]], use_container_width=True,
                         hide_index=True, on_select="ignore")
            st.caption("数据源：QMT 本地行情（延迟 2-5 秒）· 15 秒缓存")
    except ImportError:
        st.info("xtquant 未安装（pip install xtquant）")

# ── Tab 2: 财经快讯 ──
with tab_n:
    @st.cache_data(ttl=120, show_spinner=False)
    def flash_news(n: int = 30) -> pd.DataFrame:
        import akshare as ak
        df = ak.stock_info_global_em()
        return df.head(n)
    try:
        with st.spinner("拉取快讯…"):
            news = flash_news()
        for _, r in news.iterrows():
            st.markdown(
                f'<div style="padding:6px 0; border-bottom:1px solid #1E293B;">'
                f'<span style="color:{TEXT_DIM}; font-size:11px; font-family:monospace;">'
                f'{r["发布时间"][11:]}</span>　'
                f'<a href="{r["链接"]}" target="_blank" style="color:inherit; '
                f'text-decoration:none;">{r["标题"]}</a></div>',
                unsafe_allow_html=True)
        st.caption(f"{len(news)} 条 · 东财全球快讯 · 2 分钟缓存 · 点击标题打开原文")
    except Exception as e:  # noqa: BLE001
        st.warning(f"快讯拉取失败：{type(e).__name__}（东财接口限流时约 5-40 分钟恢复）")

# ── Tab 3: 自选股行情（持仓 + ETF） ──
with tab_s:
    codes = list(dict.fromkeys(load_positions() + ["518880", "513100"]))
    if not codes:
        st.info(t("暂无数据"))
    else:
        if st.button(f"🔄 {t('刷新')}", key="watch"):
            st.cache_data.clear()

        @st.cache_data(ttl=15, show_spinner=False)
        def watch_quotes(code_list: tuple) -> pd.DataFrame:
            from xtquant import xtdata
            syms = [to_sym(c) for c in code_list]
            ticks = xtdata.get_full_tick(syms) or {}
            rows = []
            for sym, d in ticks.items():
                if not d:
                    continue
                code = sym.split(".")[0]
                last = d.get("lastPrice", 0)
                ask1 = (d.get("askPrice") or [0])[0]
                bid1 = (d.get("bidPrice") or [0])[0]
                vol = d.get("volume", 0)
                amount = d.get("amount", 0)
                rows.append({
                    "代码": code, "最新价": last, "买一": ask1, "卖一": bid1,
                    "成交量": vol, "成交额": amount,
                })
            return pd.DataFrame(rows)

        try:
            dfw = watch_quotes(tuple(codes))
            if dfw.empty:
                st.info("xtdata 未返回行情（QMT 客户端未启动？）")
            else:
                names = load_names()
                dfw.insert(1, "名称", dfw["代码"].map(
                    lambda c: names.get(c, ETF_NAMES.get(c, "—")))
                if "代码" in dfw else "—")
                st.dataframe(dfw, use_container_width=True, hide_index=True,
                             on_select="ignore")
                st.caption(f"{len(dfw)} 只 · 持仓+ETF · QMT 实时（15 秒缓存）")
        except ImportError:
            st.info("xtquant 未安装")
