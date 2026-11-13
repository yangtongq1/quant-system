"""持仓与订单页（终端风格重做 + A股持仓增强：名称/最新市值/权重 + 权重环形图）"""
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from web import charts
from web.i18n import t
from web.theme import ACCENT, DOWN, TEXT_DIM, UP, inject_css, kpi_card, kpi_grid

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
def last_price2(code: str) -> tuple[float | None, float | None]:
    """（最新收盘价, 昨收价）原始价口径——算市值/盈亏/当日涨跌幅用。"""
    p = ROOT / "data" / "bars" / f"{code}.parquet"
    if not p.exists():
        return None, None
    try:
        df = pd.read_parquet(p, columns=["close"])
        n = len(df)
        if not n:
            return None, None
        last = float(df["close"].iloc[-1])
        prev = float(df["close"].iloc[-2]) if n >= 2 else None
        return last, prev
    except Exception:  # noqa: BLE001
        return None, None


def _fallback_px(code: str) -> tuple[float | None, float | None]:
    """缺行情持仓兜底（ST/退市被数据层过滤无 parquet）：xtdata 实时 → 台账成本价。"""
    try:
        from xtquant import xtdata  # type: ignore
        tick = xtdata.get_full_tick([f"{code}.SH" if code.startswith("6") else f"{code}.SZ"])
        if tick and code in tick:
            px = float(tick[code].get("lastPrice") or 0)
            if px > 0:
                return px, None
    except Exception:  # noqa: BLE001
        pass
    try:
        with sqlite3.connect(str(ROOT / "data" / "quant.db")) as conn:
            row = conn.execute(
                "SELECT avg_cost FROM positions WHERE code=?", (code,)).fetchone()
            if row and row[0]:
                return float(row[0]), None
    except Exception:  # noqa: BLE001
        pass
    return None, None


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
            px, prev = last_price2(code)
            if px is None:
                px, prev = _fallback_px(code)
            vol = int(r["volume"])
            cost = float(r["avg_cost"] or 0)
            mv = px * vol if px else None
            cost_amt = cost * vol if cost else None
            # 当日涨跌幅：最新收盘 vs 昨收（缺昨收显示 -）
            chg = None
            if px and prev:
                chg = px / prev - 1
            rows.append({
                "code": code,
                "名称": names.get(code, ETF_NAMES.get(code, "")),
                "持股数": vol,
                "成本价": round(cost, 3) if cost else None,
                "最新价": round(px, 3) if px else None,
                "当日涨跌幅": f"{chg:+.2%}" if chg is not None else "-",
                "市值": round(mv, 0) if mv else None,
                "成本金额": round(cost_amt, 0) if cost_amt else None,
                "持仓盈亏": round(mv - cost_amt, 0) if (mv and cost_amt) else None,
                "类别": "ETF" if code in ETF_NAMES else "A股",
            })
        df = pd.DataFrame(rows)
        if df["市值"].notna().any():
            total_mv = df["市值"].sum()
            total_cost = df["成本金额"].fillna(0).sum()
            total_pnl = df["持仓盈亏"].fillna(0).sum()
            # 当日涨跌金额：Σ (最新收盘-昨收)×持股数（有昨收的持仓）
            day_pnl = 0.0
            for _, r in pos.iterrows():
                code = str(r["code"])
                px, prev = last_price2(code)
                if px and prev and int(r["volume"]) > 0:
                    day_pnl += (px - prev) * int(r["volume"])
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

            total_asset = total_mv + cash

            st.markdown(f'<div class="panel-title">{t("持仓概览")} / HOLDINGS</div>',
                        unsafe_allow_html=True)
            st.markdown(kpi_grid([
                kpi_card(t("合计市值"), f"{total_mv:,.0f}", t("最新收盘价口径")),
                kpi_card(t("持仓成本"), f"{total_cost:,.0f}", f"{len(df)} 只持仓"),
                kpi_card(t("当日涨跌"), f"{day_pnl:+,.0f}",
                         f"{'上涨' if day_pnl > 0 else '下跌'}金额",
                         cls="kpi-up" if day_pnl > 0 else "kpi-down" if day_pnl < 0 else None),
                kpi_card(t("持仓盈亏"), f"{total_pnl:+,.0f}",
                         f"{(total_pnl / total_cost):+.2%}" if total_cost else "",
                         cls="kpi-up" if total_pnl > 0 else "kpi-down" if total_pnl < 0 else None),
                kpi_card(t("总资产"), f"{total_asset:,.0f}", f"市值 + 现金 {cash:,.0f}"),
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
