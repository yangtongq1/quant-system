"""Web 看板主入口（M7 · Bloomberg 终端风格重做版）

启动：streamlit run web/app.py → http://127.0.0.1:8765
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from web.i18n import lang_selector, t
from web.theme import (ACCENT, GOLD, NASDAQ, UP, DOWN, TEXT_DIM, inject_css,
                       kpi_card, kpi_grid)

st.set_page_config(page_title="QUANT TERMINAL · 金融工作台",
                   page_icon="◉", layout="wide")

st.markdown(inject_css(), unsafe_allow_html=True)

lang_selector("main")


@st.cache_data(ttl=60)
def load_equity() -> pd.Series:
    f = ROOT / "report" / "equity.csv"
    if not f.exists():
        return pd.Series(dtype=float)
    df = pd.read_csv(f, parse_dates=["date"]).set_index("date")["equity"]
    return df


@st.cache_data(ttl=60)
def system_status() -> dict:
    bars_dir = ROOT / "data" / "bars"
    return {
        "n_bars": len(list(bars_dir.glob("*.parquet"))) if bars_dir.exists() else 0,
        "has_db": (ROOT / "data" / "quant.db").exists(),
        "n_reports": len(list((ROOT / "report").glob("*.md")))
        if (ROOT / "report").exists() else 0,
    }


def main():
    # ── 顶栏 ──
    st.markdown(f"""
    <div style="display:flex; align-items:baseline; gap:14px; margin-bottom:4px;">
        <span style="font-size:26px; font-weight:800; letter-spacing:.06em;
                     font-family:'JetBrains Mono',Consolas,monospace; color:{ACCENT};">
            ◉ QUANT TERMINAL
        </span>
        <span style="color:{TEXT_DIM}; font-size:13px;">金融工作台 · 跨资产对冲配置</span>
        <span style="margin-left:auto; font-size:12px; color:{TEXT_DIM};
                     font-family:'JetBrains Mono',Consolas,monospace;">
            <span class="live-dot green"></span>ONLINE
        </span>
    </div>
    """, unsafe_allow_html=True)
    st.markdown('<hr style="border:0; border-top:1px solid #1E293B; margin:8px 0 4px 0;">',
                unsafe_allow_html=True)

    # ── 系统状态 KPI ──
    s = system_status()
    eq = load_equity()

    st.markdown('<div class="panel-title">SYSTEM / 系统状态</div>',
                unsafe_allow_html=True)
    cards = [
        kpi_card("本地行情标的", f"{s['n_bars']:,}", "Parquet 日线库"),
        kpi_card("数据库", "● 已初始化" if s["has_db"] else "○ 未初始化",
                 "SQLite 元数据/财报", cls="kpi-up" if s["has_db"] else "kpi-down"),
        kpi_card("回测报告", f"{s['n_reports']}", "report/ 目录"),
        kpi_card("核心策略", "跨资产对冲", "A股×黄金×纳指 · λ 并轨"),
    ]
    st.markdown(kpi_grid(cards), unsafe_allow_html=True)

    # ── 最新回测摘要 ──
    if not eq.empty:
        from web.charts import equity_chart, drawdown_chart
        total_ret = eq.iloc[-1] / eq.iloc[0] - 1
        peak = eq.cummax()
        dd = (eq / peak - 1).min()
        ann_ret = (eq.iloc[-1] / eq.iloc[0]) ** (252 / max(len(eq), 1)) - 1
        ann_vol = eq.pct_change().std() * (252 ** 0.5)
        sharpe = (ann_ret - 0.02) / ann_vol if ann_vol > 0 else 0
        n_years = len(eq) / 252

        st.markdown('<div class="panel-title">LAST BACKTEST / 最新回测 · λ=0.9 进取</div>',
                    unsafe_allow_html=True)
        cards = [
            kpi_card("累计收益", f"{total_ret:+.2%}", f"{n_years:.1f} 年区间",
                     cls="kpi-up" if total_ret >= 0 else "kpi-down"),
            kpi_card("年化收益", f"{ann_ret:+.2%}", "复利口径",
                     cls="kpi-up" if ann_ret >= 0 else "kpi-down"),
            kpi_card("最大回撤", f"{dd:.2%}", "水下曲线见下", cls="kpi-down"),
            kpi_card("夏普比率", f"{sharpe:.3f}", "rf = 2%"),
            kpi_card("年化波动", f"{ann_vol:.2%}", "日频年化"),
        ]
        st.markdown(kpi_grid(cards), unsafe_allow_html=True)

        c1, c2 = st.columns([2, 1])
        with c1:
            st.markdown('<div class="panel-title">EQUITY / 净值曲线</div>',
                        unsafe_allow_html=True)
            st.plotly_chart(equity_chart(eq, initial=float(eq.iloc[0])),
                            use_container_width=True,
                            config={"displayModeBar": False})
        with c2:
            st.markdown('<div class="panel-title">DRAWDOWN / 水下曲线</div>',
                        unsafe_allow_html=True)
            st.plotly_chart(drawdown_chart(eq), use_container_width=True,
                            config={"displayModeBar": False})
    else:
        st.info("暂无回测结果。运行 python main.py backtest --strategy cross_asset 生成。")

    st.divider()
    st.caption("⚠️ 研究/模拟用途，不构成投资建议。SuperMind 实盘对接待数据基建完成后接入。")


if __name__ == "__main__":
    main()
