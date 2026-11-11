"""个股K线页：K线 + MA5/20/60 均线 + 我方买卖点标注（orders/trades 箭头）。

- 选择器：持仓优先（默认第一持仓），支持全部管理范围标的
- K 线复用 charts.candlestick，叠加均线层（后复权价格口径）
- 买卖点：trades 表按 code 过滤，买=红上箭头，卖=绿下箭头
- 52 周高低 / 近 1 年涨跌 / 距离成本
"""
import sqlite3
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from web import charts
from web.i18n import lang_selector, t
from web.theme import ACCENT, DOWN, GOLD, TEXT_DIM, UP, inject_css, kpi_card, kpi_grid

lang_selector()
st.set_page_config(page_title="个股K线 · QUANT TERMINAL", layout="wide")
st.markdown(inject_css(), unsafe_allow_html=True)

st.markdown(f"""
<div class="page-title">◈ {t("个股K线")} / STOCK CHART</div>
<div style="color:{TEXT_DIM}; font-size:12px; margin-bottom:10px;">
    K线 + MA5/20/60 · {t("买卖点标注")}（我方成交） · 后复权口径</div>
""", unsafe_allow_html=True)

ETF_NAMES = {"518880": "黄金ETF", "513100": "纳指ETF"}


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


@st.cache_data(ttl=60)
def load_positions() -> pd.DataFrame:
    db = ROOT / "data" / "quant.db"
    if not db.exists():
        return pd.DataFrame()
    with sqlite3.connect(str(db)) as conn:
        try:
            return pd.read_sql(
                "SELECT code, volume, avg_cost FROM positions WHERE volume > 0", conn)
        except Exception:  # noqa: BLE001
            return pd.DataFrame()


@st.cache_data(ttl=60)
def load_tradable_codes() -> list[str]:
    """持仓 ∪ 历史成交过的标的（管理范围）"""
    db = ROOT / "data" / "quant.db"
    if not db.exists():
        return []
    with sqlite3.connect(str(db)) as conn:
        try:
            rows = conn.execute(
                "SELECT DISTINCT code FROM trades "
                "UNION SELECT code FROM positions WHERE volume > 0").fetchall()
            return sorted(r[0] for r in rows)
        except Exception:  # noqa: BLE001
            return []


@st.cache_data(ttl=60)
def load_my_trades(code: str) -> pd.DataFrame:
    """我方成交流水（按 code）"""
    db = ROOT / "data" / "quant.db"
    if not db.exists():
        return pd.DataFrame()
    with sqlite3.connect(str(db)) as conn:
        try:
            df = pd.read_sql(
                f"SELECT * FROM trades WHERE code = '{code}' ORDER BY time", conn)
        except Exception:  # noqa: BLE001
            return pd.DataFrame()
    if not df.empty:
        df["time"] = pd.to_datetime(df["time"], errors="coerce")
        df = df.dropna(subset=["time"])
    return df


@st.cache_data(ttl=300)
def load_bars(code: str) -> pd.DataFrame:
    """加载K线：展示用原始价格（行情软件口径）；adj_* 列另存复权序列（算涨跌幅用）。

    复权序列用途：近1年涨跌/52周高低等区间指标——原始价遇除权会跳空失真。
    """
    p = ROOT / "data" / "bars" / f"{code}.parquet"
    if not p.exists():
        return pd.DataFrame()
    try:
        df = pd.read_parquet(p)
        df["date"] = pd.to_datetime(df["date"])
        # 原始价格保留 open/high/low/close（展示口径）
        # 复权序列存到 adj_close/adj_high/adj_low（计算口径）
        for c in ("close", "high", "low"):
            df[f"adj_{c}"] = df[c] * df["adj_factor"]
        return df.sort_values("date").reset_index(drop=True)
    except Exception:  # noqa: BLE001
        return pd.DataFrame()


# ── 选择器 ──
pos = load_positions()
all_codes = load_tradable_codes()
names = load_names()

if not all_codes:
    st.warning(t("暂无数据"))
    st.stop()

pos_codes = [str(c) for c in pos["code"].tolist()] if not pos.empty else []
# 持仓在前
ordered = list(dict.fromkeys(pos_codes + all_codes))


def label_of(c: str) -> str:
    n = names.get(c, ETF_NAMES.get(c, ""))
    return f"{c} {n}" if n else c


c1, c2, c3 = st.columns([2, 1, 1])
with c1:
    code = st.selectbox(t("代码"), ordered, index=0, format_func=label_of)
with c2:
    window = st.selectbox(t("时间窗口"), ["120", "250", "500", "全部"],
                          index=1)
with c3:
    st.write("")

bars = load_bars(code)
if bars.empty:
    st.warning(f"{code} 无本地K线（data/bars/{code}.parquet 缺失）")
    st.stop()

n_show = len(bars) if window == "全部" else int(window)
d = bars.tail(n_show).copy().reset_index(drop=True)
last_price = float(bars["close"].iloc[-1])          # 原始价（展示口径）
adj_last = float(bars["adj_close"].iloc[-1])        # 复权价（计算口径）

# ── KPI ──
w52 = bars.tail(252)
hi52 = float(w52["adj_high"].max())   # 复权口径（跨除权不失真）
lo52 = float(w52["adj_low"].min())
if len(w52) >= 232:  # 约满一年
    y1_chg = adj_last / float(w52["adj_close"].iloc[0]) - 1
else:
    y1_chg = None
my_trades = load_my_trades(code)
buy_amt = my_trades.loc[my_trades["side"] == "buy", "volume"].sum() if not my_trades.empty else 0
sell_amt = my_trades.loc[my_trades["side"] == "sell", "volume"].sum() if not my_trades.empty else 0
row = pos[pos["code"] == code]
cost = float(row["avg_cost"].iloc[0]) if len(row) else None
pnl = (last_price / cost - 1) if cost else None   # 原始价 vs 真实成本价

cards = [
    kpi_card(t("最新价"), f"{last_price:.2f}", t("原始价")),
    kpi_card(t("52周最高"), f"{hi52:.2f}", t("复权价")),
    kpi_card(t("52周最低"), f"{lo52:.2f}", t("复权价")),
    kpi_card(t("近1年涨跌"), f"{y1_chg:.2%}" if y1_chg is not None else "—",
             t("不足一年") if y1_chg is None else "",
             cls="kpi-up" if (y1_chg or 0) >= 0 else "kpi-down"),
]
if pnl is not None:
    cards.append(kpi_card(t("持仓盈亏"), f"{pnl:.2%}",
                          f"成本 {cost:.3f}",
                          cls="kpi-up" if pnl >= 0 else "kpi-down"))
st.markdown(kpi_grid([c for c in cards if c]), unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True)

# ── K线 + 均线 + 买卖点 ──
st.markdown(
    f'<div class="panel-title">{label_of(code)} · K线 / CANDLESTICK</div>',
    unsafe_allow_html=True)

import plotly.graph_objects as go

fig = charts.candlestick(d, title="")

# 均线（原始收盘价——与K线同口径）
for w, colr in ((5, GOLD), (20, ACCENT), (60, "#94A3B8")):
    ma = d["close"].rolling(w).mean()
    fig.add_trace(go.Scatter(
        x=d["date"], y=ma, name=f"MA{w}", mode="lines",
        line=dict(color=colr, width=1.2),
        hovertemplate=f"MA{w} %{{y:.3f}}<extra></extra>",
    ), row=1, col=1)

# 我方买卖点标注（成交价 × 复权因子对齐 → 用当日收盘价近似位置，箭头标记）
if not my_trades.empty:
    dset = d.set_index("date")
    for side, sym, colr, dy in (("buy", "triangle-up", UP, 1.0),
                                ("sell", "triangle-down", DOWN, 1.0)):
        sub = my_trades[my_trades["side"] == side]
        if sub.empty:
            continue
        # 映射到展示窗口内的日期
        rows = []
        for _, tr in sub.iterrows():
            day = tr["time"].normalize()
            # 找 <= 成交日的最近K线
            idx = dset.index.searchsorted(day, side="right") - 1
            if idx < 0 or idx >= len(dset):
                continue
            dt = dset.index[idx]
            rows.append({"date": dt, "price": float(dset["close"].iloc[idx]),
                         "volume": int(tr["volume"]), "p": float(tr["price"])})
        if not rows:
            continue
        mdf = pd.DataFrame(rows)
        # 同日多笔合并
        mdf = mdf.groupby("date", as_index=False).agg(
            {"price": "first", "volume": "sum", "p": "mean"})
        off = (d["high"].max() - d["low"].min()) * 0.04
        yv = (mdf["price"] + off) if side == "buy" else (mdf["price"] - off)
        fig.add_trace(go.Scatter(
            x=mdf["date"], y=yv, name=f"{t('买入') if side == 'buy' else t('卖出')}",
            mode="markers",
            marker=dict(symbol=sym, size=13, color=colr,
                        line=dict(color="#FFFFFF", width=0.8)),
            customdata=mdf[["volume", "p"]],
            hovertemplate=("%{x|%Y-%m-%d}<br>"
                           + t("数量") + " %{customdata[0]}<br>"
                           + t("价格") + " %{customdata[1]:.3f}<extra></extra>"),
        ), row=1, col=1)

fig.update_layout(showlegend=True, legend=dict(
    orientation="h", y=1.12, font=dict(color=TEXT_DIM, size=11)))
st.plotly_chart(fig, use_container_width=True)

st.caption(f"{t('数据区间')} {d['date'].iloc[0]:%Y-%m-%d} ~ {d['date'].iloc[-1]:%Y-%m-%d} · "
           f"{len(d)} {t('个交易日')} · {t('原始价')} · "
          f"{t('买卖点标注')}: {len(my_trades)} {t('笔')}（买 {int(buy_amt)} / 卖 {int(sell_amt)}）")

# ── 我方成交流水明细 ──
if not my_trades.empty:
    with st.expander(f"📋 {t('我方成交明细')}（{code}）", expanded=False):
        show = my_trades.copy()
        show["方向"] = show["side"].map({"buy": t("买入"), "sell": t("卖出")})
        show = show.rename(columns={
            "price": t("价格"), "volume": t("数量"), "fee": t("费用"),
            "time": t("时间")})
        st.dataframe(show[[t("时间"), t("方向"), t("价格"), t("数量"), t("费用")]],
                     use_container_width=True, hide_index=True, on_select="ignore")
