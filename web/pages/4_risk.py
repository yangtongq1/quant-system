"""风控状态页（终端风格重做：表盘 + 压力测试）"""
import json
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from web.theme import ACCENT, TEXT_DIM, inject_css, kpi_card, kpi_grid

st.set_page_config(page_title="风控状态 · QUANT TERMINAL", layout="wide")
st.markdown(inject_css(), unsafe_allow_html=True)

from web.charts import correlation_gauge

st.markdown(f"""
<div style="font-size:22px; font-weight:800; letter-spacing:.04em;
             font-family:'JetBrains Mono',Consolas,monospace; color:{ACCENT};">
    ◈ RISK CONTROL
</div>
<div style="color:{TEXT_DIM}; font-size:12px; margin-bottom:10px;">
    事前拦截 / 事中监控 / 事后复盘 · 对冲失效监控 · 压力测试</div>
""", unsafe_allow_html=True)

# ── 相关性表盘（对冲失效监控）──
corr_file = ROOT / "report" / "correlation.json"
if corr_file.exists():
    data = json.loads(corr_file.read_text(encoding="utf-8"))
    st.markdown('<div class="panel-title">HEDGE MONITOR / 对冲失效监控（|ρ| &gt; 0.5 告警）</div>',
                unsafe_allow_html=True)
    g1, g2, info = st.columns([1, 1, 1.2])
    with g1:
        st.plotly_chart(correlation_gauge(float(data.get("gold_stock_corr", 0)),
                                          "黄金 × A股"),
                        use_container_width=True, config={"displayModeBar": False})
    with g2:
        st.plotly_chart(correlation_gauge(float(data.get("nasdaq_stock_corr", 0)),
                                          "纳指 × A股"),
                        use_container_width=True, config={"displayModeBar": False})
    with info:
        gs = data.get("gold_stock_corr", 0)
        ns = data.get("nasdaq_stock_corr", 0)
        st.markdown(kpi_grid([
            kpi_card("监控日期", str(data.get("date", "—"))),
            kpi_card("系统状态", str(data.get("status", "—")).upper(),
                     cls="kpi-up" if data.get("status") == "ok" else "kpi-down"),
            kpi_card("联动解读", "分散有效" if max(abs(gs), abs(ns)) < 0.5 else "警惕联动",
                     cls="kpi-up" if max(abs(gs), abs(ns)) < 0.5 else "kpi-down"),
        ]), unsafe_allow_html=True)
        st.caption("黄金与 A 股相关性走强意味着避险属性弱化；纳指与 A 股同涨跌意味着跨市场分散失效。"
                   "2020 疫情期实测 ρ=0.67，正是需求文档要求监控的场景。")
else:
    st.info("暂无相关性监控数据。运行 python main.py monitor 生成。")

st.divider()

# ── 压力测试 ──
st.markdown('<div class="panel-title">STRESS TEST / 历史压力场景</div>', unsafe_allow_html=True)
stress_file = ROOT / "report" / "stress_test.csv"
if stress_file.exists():
    df = pd.read_csv(stress_file)
    rows = ""
    for _, r in df.iterrows():
        ret = float(r["return"])
        cls = "up" if ret >= 0 else "down"
        rows += (
            f"<tr><td>{r['label']}</td>"
            f"<td class='mono'>{r['start']} ~ {r['end']}</td>"
            f"<td class='mono'>{int(r['n_days'])}d</td>"
            f"<td class='{cls}'>{ret:+.2%}</td>"
            f"<td class='down'>{float(r['max_drawdown']):.2%}</td>"
            f"<td class='down'>{float(r['worst_day']):.2%}</td>"
            f"<td class='up'>{r['status']}</td></tr>"
        )
    st.markdown(f"""
    <table class="data-table">
        <thead><tr><th>场景</th><th>区间</th><th>天数</th><th>收益</th>
        <th>最大回撤</th><th>最差单日</th><th>状态</th></tr></thead>
        <tbody>{rows}</tbody>
    </table>
    """, unsafe_allow_html=True)
else:
    st.info("暂无压力测试结果。运行 python main.py stress 生成。")

st.divider()

# ── 风控事件流 ──
st.markdown('<div class="panel-title">EVENT LOG / 风控事件（追加只读）</div>', unsafe_allow_html=True)
events_file = ROOT / "report" / "risk_events.json"
if events_file.exists():
    events = json.loads(events_file.read_text(encoding="utf-8"))
    if events:
        df = pd.DataFrame(events)
        rejects = int((df["type"] == "pre_trade_reject").sum()) if "type" in df else 0
        alerts = int(df["type"].astype(str).str.contains("alert").sum()) if "type" in df else 0
        st.markdown(kpi_grid([
            kpi_card("事前拦截", f"{rejects}", cls="kpi-down" if rejects else "kpi-up"),
            kpi_card("事中/事后告警", f"{alerts}", cls="kpi-down" if alerts else "kpi-up"),
            kpi_card("事件总数", f"{len(df)}"),
        ]), unsafe_allow_html=True)
        st.dataframe(df, use_container_width=True, hide_index=True)
    else:
        st.success("无风控事件——一切正常。")
else:
    st.info("暂无风控事件记录。回测/模拟盘触发风控时自动留痕。")
