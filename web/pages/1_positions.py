"""持仓与订单页（终端风格重做 + A股持仓增强：名称/最新市值/权重 + 权重环形图）"""
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from web import charts
from web.i18n import lang_selector, t
from web.theme import ACCENT, DOWN, TEXT_DIM, UP, inject_css, kpi_card, kpi_grid

lang_selector()
st.set_page_config(page_title="持仓与订单 · QUANT TERMINAL", layout="wide")
st.markdown(inject_css(), unsafe_allow_html=True)

import sqlite3

ETF_NAMES = {"518880": "黄金ETF", "513100": "纳指ETF"}


@st.cache_data(ttl=30)
def load_table(table: str) -> pd.DataFrame:
    db = ROOT / "data" / "quant.db"
    if not db.exists():
        return pd.DataFrame()
    with sqlite3.connect(str(db)) as conn:
        try:
            return pd.read_sql(f"SELECT * FROM {table} ORDER BY rowid DESC", conn)
        except Exception:  # noqa: BLE001
            return pd.DataFrame()


@st.cache_data(ttl=30)
def load_names() -> dict:
    """code -> 股票名称（stocks 表）"""
    db = ROOT / "data" / "quant.db"
    if not db.exists():
        return {}
    with sqlite3.connect(str(db)) as conn:
        try:
            df = pd.read_sql("SELECT code, name FROM stocks", conn)
            return dict(zip(df["code"].astype(str), df["name"]))
        except Exception:  # noqa: BLE001
            return {}


@st.cache_data(ttl=30)
def last_price(code: str) -> float | None:
    """最新收盘价（原始价——与真实持仓股数/成本价同口径，算市值/盈亏用）"""
    p = ROOT / "data" / "bars" / f"{code}.parquet"
    if not p.exists():
        return None
    try:
        df = pd.read_parquet(p, columns=["close"])
        if not len(df):
            return None
        return float(df["close"].iloc[-1])
    except Exception:  # noqa: BLE001
        return None


st.markdown(f"""
<div class="page-title">◈ {t("持仓与订单")} / POSITIONS & ORDERS</div>
<div style="color:{TEXT_DIM}; font-size:12px; margin-bottom:10px;">{t("持仓 · 订单 · 成交流水 · A股 + ETF")}</div>
""", unsafe_allow_html=True)

tabs = st.tabs([f"◎ {t('持仓')}", f"◎ {t('订单')}", f"◎ {t('成交流水')}"])

# ── Tab 1: 持仓（增强版） ──
with tabs[0]:
    pos = load_table("positions")
    if pos.empty:
        tabs[0].info("暂无持仓。控制台「执行模块」运行模拟盘信号，或 python main.py run-paper。")
    else:
        names = load_names()
        rows = []
        for _, r in pos.iterrows():
            code = str(r["code"])
            px = last_price(code)
            vol = int(r["volume"])
            mv = px * vol if px else None
            rows.append({
                "code": code,
                "名称": names.get(code, ETF_NAMES.get(code, "")),
                "持股数": vol,
                "成本价": r["avg_cost"] or None,
                "最新价": round(px, 3) if px else None,
                "市值": round(mv, 0) if mv else None,
                "类别": "ETF" if code in ETF_NAMES else "A股",
            })
        df = pd.DataFrame(rows)
        if df["市值"].notna().any():
            total_mv = df["市值"].sum()
            df["权重"] = (df["市值"] / total_mv).map(lambda v: f"{v:.2%}")
            df = df.sort_values("市值", ascending=False, na_position="last")
            # KPI 摘要
            n_a = int((df["类别"] == "A股").sum())
            n_e = int((df["类别"] == "ETF").sum())
            a_mv = df.loc[df["类别"] == "A股", "市值"].sum()
            e_mv = df.loc[df["类别"] == "ETF", "市值"].sum()

            # 现金（accounts 表）
            try:
                with sqlite3.connect(str(ROOT / "data" / "quant.db")) as conn:
                    cash = conn.execute(
                        "SELECT cash FROM accounts ORDER BY rowid DESC LIMIT 1"
                    ).fetchone()
                    cash = float(cash[0]) if cash else 0.0
            except Exception:  # noqa: BLE001
                cash = 0.0

            st.markdown(f'<div class="panel-title">{t("持仓概览")} / HOLDINGS</div>',
                        unsafe_allow_html=True)
            st.markdown(kpi_grid([
                kpi_card(t("持仓总数"), f"{len(df)}", f"A股 {n_a} + ETF {n_e}"),
                kpi_card(t("A股仓位市值"), f"{a_mv:,.0f}", t("按最新收盘价"),
                         cls="kpi-up" if a_mv > 0 else None),
                kpi_card(t("ETF仓位市值"), f"{e_mv:,.0f}", t("黄金+纳指"),
                         cls="kpi-up" if e_mv > 0 else None),
                kpi_card(t("合计市值"), f"{total_mv:,.0f}", t("最新收盘价口径")),
                kpi_card(t("可用现金"), f"{cash:,.0f}", t("账户余额")),
            ]), unsafe_allow_html=True)

            # 权重环形图（A股 / 黄金 / 纳指 / 现金）
            gold_mv = df.loc[df["code"] == "518880", "市值"].sum() if (df["code"] == "518880").any() else 0.0
            nasdaq_mv = df.loc[df["code"] == "513100", "市值"].sum() if (df["code"] == "513100").any() else 0.0
            stock_mv = max(a_mv - gold_mv - nasdaq_mv, 0.0)
            st.markdown(f'<div class="panel-title">{t("资产权重分布")} / ALLOCATION</div>',
                        unsafe_allow_html=True)
            st.plotly_chart(
                charts.asset_weight_donut(
                    {"stock_value": stock_mv, "cash": cash}, gold_mv, nasdaq_mv),
                use_container_width=True)
        st.markdown(f'<div class="panel-title">{t("持仓明细")} / DETAIL</div>',
                    unsafe_allow_html=True)
        st.dataframe(df, use_container_width=True, hide_index=True, on_select="ignore")
        tabs[0].caption(f"{len(df)} 条持仓 · 市值按最新收盘价（原始价）计算 · 30 秒缓存自动刷新")

# ── Tab 2/3: 订单 / 成交流水 ──
for tab, table in zip(tabs[1:], ["orders", "trades"]):
    with tab:
        df = load_table(table)
        if df.empty:
            tab.info(f"暂无 {table} 数据。运行 python main.py run-paper 启动模拟盘。")
        else:
            tab.dataframe(df, use_container_width=True, hide_index=True, on_select="ignore")
            tab.caption(f"{len(df)} 条记录 · 最近 30 秒自动刷新缓存")
