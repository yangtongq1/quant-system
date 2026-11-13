"""今日交易计划页（盘前可查：当日策略生成的买入/卖出计划）"""
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from web.i18n import t
from web.theme import ACCENT, DOWN, TEXT_DIM, UP, inject_css, kpi_card, kpi_grid

st.set_page_config(page_title="今日交易计划 · QUANT TERMINAL", layout="wide")
st.markdown(inject_css(), unsafe_allow_html=True)

ETF_NAMES = {"518880": "黄金ETF", "513100": "纳指ETF", "510300": "沪深300ETF"}


@st.cache_data(ttl=15)
def load_today_orders() -> pd.DataFrame:
    """当日 orders（盘前 run-paper 生成并 QMT 委托的买卖计划）。"""
    db = ROOT / "data" / "quant.db"
    if not db.exists():
        return pd.DataFrame()
    today = datetime.now().strftime("%Y-%m-%d")
    with sqlite3.connect(str(db)) as conn:
        try:
            return pd.read_sql(
                "SELECT * FROM orders WHERE create_time LIKE ? ORDER BY rowid",
                conn, params=(f"{today}%",))
        except Exception:  # noqa: BLE001
            return pd.DataFrame()


@st.cache_data(ttl=60)
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


@st.cache_data(ttl=15)
def last_close(code: str) -> float | None:
    p = ROOT / "data" / "bars" / f"{code}.parquet"
    if not p.exists():
        return None
    try:
        return float(pd.read_parquet(p, columns=["close"])["close"].iloc[-1])
    except Exception:  # noqa: BLE001
        return None


st.markdown(f"""
<div class="page-title">◈ {t("今日交易计划")} / TODAY'S TRADE PLAN</div>
<div style="color:{TEXT_DIM}; font-size:12px; margin-bottom:10px;">{t("盘前 08:30 策略生成 · 开盘前可查当日买卖计划 · 数据源 orders 表")}</div>
""", unsafe_allow_html=True)

orders = load_today_orders()
now = datetime.now()
today_str = now.strftime("%Y-%m-%d %H:%M")

if orders.empty:
    # 区分「还没生成」与「今日无需调仓」
    st.info(f"今日（{today_str}）暂无交易计划。"
            f"盘前任务 08:30 自动生成；也可控制台手动运行 run-paper。")
    st.caption("调度链路：盘后 15:05 数据增量 → 次日盘前 08:30 策略生成+QMT 委托。"
               "周末/节假日不生成。")
    st.stop()

names = load_names()
rows = []
for _, r in orders.iterrows():
    code = str(r["code"])
    px = float(r["price"] or 0)
    vol = int(r["volume"] or 0)
    amt = px * vol
    lc = last_close(code)
    rows.append({
        "方向": str(r["side"]),
        "代码": code,
        "名称": names.get(code, ETF_NAMES.get(code, "")),
        "数量": vol,
        "委托价": round(px, 3),
        "最新收盘": round(lc, 3) if lc else None,
        "金额": round(amt, 0),
        "状态": str(r.get("status", "")),
    })
df = pd.DataFrame(rows)

buys = df[df["方向"] == "buy"]
sells = df[df["方向"] == "sell"]
buy_amt = buys["金额"].fillna(0).sum()
sell_amt = sells["金额"].fillna(0).sum()

st.markdown(kpi_grid([
    kpi_card(t("买入笔数"), f"{len(buys)}", f"金额 {buy_amt:,.0f}", cls="kpi-up"),
    kpi_card(t("卖出笔数"), f"{len(sells)}", f"金额 {sell_amt:,.0f}", cls="kpi-down"),
    kpi_card(t("净买入"), f"{buy_amt - sell_amt:+,.0f}",
             "买入 − 卖出金额",
             cls="kpi-up" if buy_amt >= sell_amt else "kpi-down"),
    kpi_card(t("计划生成时间"), today_str, "盘前任务 08:30 自动生成"),
]), unsafe_allow_html=True)

st.markdown(f'<div class="panel-title">{t("卖出计划")} / SELL ORDERS</div>',
            unsafe_allow_html=True)
if sells.empty:
    st.caption("无卖出计划")
else:
    st.dataframe(sells, use_container_width=True, hide_index=True, on_select="ignore")

st.markdown(f'<div class="panel-title">{t("买入计划")} / BUY ORDERS</div>',
            unsafe_allow_html=True)
if buys.empty:
    st.caption("无买入计划")
else:
    st.dataframe(buys, use_container_width=True, hide_index=True, on_select="ignore")

st.caption(f"共 {len(df)} 笔 · 生成于 {today_str} · 委托价为策略重放价（QMT 限价单含缓冲）"
           "· 执行顺序：先卖后买 · 15 秒自动刷新")
