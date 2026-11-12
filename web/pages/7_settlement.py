"""交割单页（中文详单 + 板块/行业细分）。

交割单语义：真实委托成交明细（外部通道模式），含方向中文化（买入/卖出）、
金额与费用、板块归属（主板/创业板/科创板/ETF）与行业细分（akshare 新浪行业
分类，实时拉取 + 缓存，拉不到时显示「—」）。
"""
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from web.i18n import lang_selector, t
from web.theme import TEXT_DIM, inject_css, kpi_card, kpi_grid

st.set_page_config(page_title="交割单 · QUANT TERMINAL", layout="wide")
lang_selector()
st.markdown(inject_css(), unsafe_allow_html=True)

import sqlite3  # noqa: E402


def board_cn(code: str) -> str:
    """代码 → 板块中文名。"""
    if code.startswith("5188"):
        return "黄金ETF（T+0）"
    if code.startswith("513"):
        return "跨境ETF（T+0）"
    if code.startswith("51") or code.startswith("56") or code.startswith("58"):
        return "ETF"
    if code.startswith(("300", "301")):
        return "创业板（T+1）"
    if code.startswith("688"):
        return "科创板（T+1）"
    if code.startswith(("600", "601", "603", "605")):
        return "沪市主板（T+1）"
    if code.startswith(("000", "001", "002", "003")):
        return "深市主板（T+1）"
    if code.startswith(("8", "4", "9")):
        return "北交所"
    return "其他"


@st.cache_data(ttl=3600, show_spinner=False)
def load_industry() -> dict[str, str]:
    """行业分类兜底（stocks.industry 列为空时的在线源，新浪备用）。"""
    try:
        import akshare as ak
        df = ak.stock_industry_clf_hist_sw()
        return dict(zip(df["股票代码"].astype(str), df["所属行业"].astype(str)))
    except Exception:  # noqa: BLE001
        return {}


@st.cache_data(ttl=30)
def load_names() -> tuple[dict, dict]:
    """(名称映射, 行业映射)——行业优先 stocks.industry 列（fetch_industry.py 采集）。"""
    db = ROOT / "data" / "quant.db"
    if not db.exists():
        return {}, {}
    with sqlite3.connect(str(db)) as conn:
        try:
            df = pd.read_sql("SELECT code, name, industry FROM stocks", conn)
            names = dict(zip(df["code"].astype(str), df["name"]))
            inds = {c: i for c, i in zip(df["code"].astype(str),
                                         df["industry"].fillna("")) if i}
            return names, inds
        except Exception:  # noqa: BLE001
            try:
                df = pd.read_sql("SELECT code, name FROM stocks", conn)
                return dict(zip(df["code"].astype(str), df["name"])), {}
            except Exception:  # noqa: BLE001
                return {}, {}


# ── 模拟盘正式起始日 ──
# 之前的委托均为调试/试错单（ETF 建仓 + 链路验证），交割单与统计从该日起计算。
PAPER_START = pd.Timestamp("2026-11-12")


@st.cache_data(ttl=30)
def load_settlement(scope: str = "all") -> pd.DataFrame:
    """交割单（外部通道真实委托成交，自模拟盘正式起始日起）。

    scope: all=自起始日全部 / 30d=近30天 / 7d=近7天 / today=今日
    """
    db = ROOT / "data" / "quant.db"
    with sqlite3.connect(str(db)) as conn:
        try:
            df = pd.read_sql(
                "SELECT * FROM orders ORDER BY create_time DESC", conn)
        except Exception:  # noqa: BLE001
            return pd.DataFrame()
    if df.empty:
        return df
    df["create_time"] = pd.to_datetime(df["create_time"], errors="coerce")
    # 正式起始日锚点：之前的调试单不计入
    df = df[df["create_time"] >= PAPER_START].copy()
    if scope == "30d":
        cutoff = pd.Timestamp.now() - pd.Timedelta(days=30)
        return df[df["create_time"] >= cutoff].copy()
    if scope == "7d":
        cutoff = pd.Timestamp.now() - pd.Timedelta(days=7)
        return df[df["create_time"] >= cutoff].copy()
    if scope == "today":
        return df[df["create_time"].dt.date == pd.Timestamp.now().date()].copy()
    return df


st.markdown(f"""
<div class="page-title">◈ {t("交割单")} / SETTLEMENT</div>
<div style="color:{TEXT_DIM}; font-size:12px; margin-bottom:10px;">
    真实委托成交明细 · 板块归属 · T+0/T+1 标注 · 双语</div>
""", unsafe_allow_html=True)

col1, col2 = st.columns([3, 1])
with col2:
    scope_labels = {t("自起始日全部"): "all", t("近30天"): "30d",
                    t("近7天"): "7d", t("今日"): "today"}
    scope_pick = st.selectbox(t("日期范围 / Days"), list(scope_labels),
                              index=0, label_visibility="collapsed")
    scope = scope_labels[scope_pick]

df = load_settlement(scope)
if df.empty:
    st.info(t("暂无数据") + "。运行 python main.py run-paper --qmt 产生真实委托。")
    st.stop()

names, industry = load_names()

rows = []
for _, r in df.iterrows():
    code = str(r["code"])
    side_zh = t("买入") if r["side"] == "buy" else t("卖出")
    status_raw = str(r["status"])
    if status_raw.startswith("SUBMITTED"):
        status_zh = t("已委托")
    elif status_raw.startswith("REJECTED"):
        status_zh = t("风控拒绝")
    elif status_raw == "FILLED":
        status_zh = t("已成交")
    elif status_raw == "SKIPPED":
        status_zh = "已跳过"
    else:
        status_zh = status_raw
    amount = float(r["price"]) * int(r["volume"])
    rows.append({
        "时间 Time": str(r["create_time"])[:19],
        "代码 Code": code,
        "名称 Name": names.get(code, "黄金ETF" if code == "518880" else "纳指ETF" if code == "513100" else "—"),
        t("方向"): side_zh,
        t("价格"): round(float(r["price"]), 3),
        t("数量"): int(r["volume"]),
        t("金额"): f"{amount:,.0f}",
        t("板块"): board_cn(code),
        t("行业"): industry.get(code, "—"),
        t("状态"): status_zh,
    })
sdf = pd.DataFrame(rows)

# KPI 摘要
buys = sdf[sdf[t("方向")] == t("买入")]
sells = sdf[sdf[t("方向")] == t("卖出")]
buy_amt = sum(float(x.replace(",", "")) for x in buys[t("金额")])
sell_amt = sum(float(x.replace(",", "")) for x in sells[t("金额")])
n_days_run = (pd.Timestamp.now() - PAPER_START).days + 1
st.markdown(kpi_grid([
    kpi_card(t("委托笔数"), f"{len(sdf)}", f"{scope_pick}"),
    kpi_card(t("买入金额"), f"{buy_amt:,.0f}", f"{len(buys)} {t('笔')}",
             cls="kpi-up"),
    kpi_card(t("卖出金额"), f"{sell_amt:,.0f}", f"{len(sells)} {t('笔')}",
             cls="kpi-down"),
    kpi_card(t("净买入"), f"{buy_amt - sell_amt:+,.0f}", t("买入-卖出")),
    kpi_card(t("正式运行"), f"{n_days_run} {t('天')}",
             f"{PAPER_START:%Y-%m-%d} {t('起')}", cls="kpi-up"),
]), unsafe_allow_html=True)

st.markdown(f'<div class="panel-title">{t("交割单")} / SETTLEMENT DETAIL</div>',
            unsafe_allow_html=True)
st.dataframe(sdf, use_container_width=True, hide_index=True, on_select="ignore")
st.caption(f"{len(sdf)} 条 · {t('模拟盘正式运行自')} {PAPER_START:%Y-%m-%d}"
           f"（{t('此前调试单不计入')}）· 30 {t('秒自动刷新')}")
