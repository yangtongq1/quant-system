"""持仓与订单页（终端风格重做）"""
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from web.theme import ACCENT, TEXT_DIM, inject_css

st.set_page_config(page_title="持仓与订单 · QUANT TERMINAL", layout="wide")
st.markdown(inject_css(), unsafe_allow_html=True)

import sqlite3


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


st.markdown(f"""
<div style="font-size:22px; font-weight:800; letter-spacing:.04em;
             font-family:'JetBrains Mono',Consolas,monospace; color:{ACCENT};">
    ◈ POSITIONS & ORDERS
</div>
<div style="color:{TEXT_DIM}; font-size:12px; margin-bottom:10px;">持仓 · 订单 · 成交流水</div>
""", unsafe_allow_html=True)

tabs = st.tabs(["◎ 持仓", "◎ 订单", "◎ 成交流水"])
for tab, table in zip(tabs, ["positions", "orders", "trades"]):
    with tab:
        df = load_table(table)
        if df.empty:
            tab.info(f"暂无 {table} 数据。运行 python main.py run-paper 启动模拟盘。")
        else:
            # 数值列右对齐 + 等宽字体
            tab.dataframe(
                df,
                use_container_width=True,
                hide_index=True,
                on_select="ignore",
            )
            tab.caption(f"{len(df)} 条记录 · 最近 30 秒自动刷新缓存")
