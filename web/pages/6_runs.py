"""运行中心页：执行留痕（console/scheduler 全部运行）+ 回测运行归档

两块内容：
  1. 执行留痕：data/console_runs.json —— 面板按钮与每日调度的每一次执行
  2. 回测归档：report/runs/ —— 每次回测的参数/指标/净值
"""
import json
import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from web.theme import ACCENT, DOWN, TEXT_DIM, UP, inject_css
from web.i18n import t

st.set_page_config(page_title="运行中心 · QUANT TERMINAL", layout="wide")
st.markdown(inject_css(), unsafe_allow_html=True)

st.markdown(f"""
<div class="page-title">◈ {t("运行中心")} / RUN CENTER</div>
<div style="color:{TEXT_DIM}; font-size:12px; margin-bottom:10px;">
    执行留痕（面板按钮 + 每日调度）· 回测归档（report/runs/）· 全量可追溯</div>
""", unsafe_allow_html=True)


# ══════════════════ 第一区：执行留痕（runs registry）══════════════════
st.markdown('<div class="panel-title">EXECUTION LOG / 执行留痕</div>',
            unsafe_allow_html=True)
try:
    from scripts.runs_registry import load_runs, stats
    stats_info = stats()
    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("累计运行", stats_info["total"])
    k2.metric("今日运行", stats_info["today"])
    k3.metric("今日成功", stats_info["today_done"])
    k4.metric("今日失败", stats_info["today_failed"])
    k5.metric("进行中", stats_info["running"])
    st.markdown("<div style='height:6px;'></div>", unsafe_allow_html=True)

    runs = load_runs(limit=200)
    if not runs:
        st.info("暂无执行留痕。控制台运行任务或调度器每日执行后自动记录。")
    else:
        badge = {
            "done": '<span style="color:#4ADE80;">✓ done</span>',
            "failed": '<span style="color:#F87171;">✗ failed</span>',
            "running": '<span class="live-dot green"></span>running',
            "aborted": '<span style="color:#FBBF24;">− aborted</span>',
        }
        trs = []
        for r in runs:
            dur = "-" if r.get("duration_s") is None else f"{r['duration_s']:.0f}s"
            st_badge = badge.get(r.get("status"), r.get("status"))
            trs.append(
                f"<tr><td>{r['ts_start']}</td>"
                f"<td>{r.get('label', r.get('key', '-'))}</td>"
                f"<td>{st_badge}</td>"
                f"<td>{dur}</td>"
                f"<td class='mono' style='font-size:11px;'>{(r.get('cmd') or '')[:70]}</td></tr>"
            )
        st.markdown(f"""
        <table class="data-table">
            <thead><tr><th>开始时间</th><th>任务</th><th>状态</th><th>耗时</th><th>命令</th></tr></thead>
            <tbody>{''.join(trs)}</tbody>
        </table>
        """, unsafe_allow_html=True)

        st.markdown("<div style='height:4px;'></div>", unsafe_allow_html=True)
        labels = [f"{r['ts_start']} · {r.get('label', r.get('key'))}" for r in runs[:50]]
        sel = st.selectbox("查看运行日志", labels, index=0, key="log_pick")
        if sel:
            pick = runs[:50][labels.index(sel)]
            log_path = Path(pick.get("log") or "")
            if log_path.exists():
                with st.expander(f"日志 · {log_path.name}", expanded=False):
                    st.code(log_path.read_text(encoding="utf-8",
                                              errors="replace")[-6000:], language="log")
            else:
                st.caption(f"日志文件不存在：{log_path}")
except Exception as e:  # noqa: BLE001
    st.warning(f"执行留痕读取异常：{e}")

st.divider()


# ══════════════════ 第二区：回测归档（report/runs/）══════════════════
st.markdown('<div class="panel-title">BACKTEST ARCHIVE / 回测归档</div>',
            unsafe_allow_html=True)


@st.cache_data(ttl=30)
def load_runs() -> list[dict]:
    runs_dir = ROOT / "report" / "runs"
    if not runs_dir.exists():
        return []
    out = []
    for run_dir in sorted(runs_dir.iterdir(), reverse=True):
        meta_file = run_dir / "run.json"
        if not meta_file.exists():
            continue
        try:
            meta = json.loads(meta_file.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        meta["_dir"] = run_dir.name
        meta["_has_equity"] = (run_dir / "equity.csv").exists()
        out.append(meta)
    return out


runs = load_runs()
if not runs:
    st.info("暂无回测归档。运行 python main.py backtest ... 后自动留痕到 report/runs/。")
    st.stop()


def fmt_pct(v):
    return f"{v:+.2%}" if isinstance(v, (int, float)) else "-"


def fmt_num(v, nd=3):
    return f"{v:.{nd}f}" if isinstance(v, (int, float)) else "-"


rows = "".join(
    f"<tr><td>{r.get('timestamp', '-')}</td>"
    f"<td>{r.get('strategy', '-')}</td>"
    f"<td>{'' if r.get('lam') is None else 'λ=' + str(r.get('lam'))}</td>"
    f"<td>{r.get('n_assets', '-')}</td>"
    f"<td>{'' if r.get('top_n') is None else r.get('top_n')}</td>"
    f"<td class='{'up' if (r.get('total_return') or 0) >= 0 else 'down'}'>{fmt_pct(r.get('total_return'))}</td>"
    f"<td>{fmt_pct(r.get('annual_return'))}</td>"
    f"<td class='down'>{fmt_pct(r.get('max_drawdown'))}</td>"
    f"<td>{fmt_num(r.get('sharpe'))}</td>"
    f"<td>{r.get('n_trades', '-')}</td>"
    f"<td>{'✓' if r.get('_has_equity') else '—'}</td></tr>"
    for r in runs
)

st.markdown(f"""
<table class="data-table">
    <thead><tr><th>时间</th><th>策略</th><th>λ</th><th>池</th><th>TopN</th>
    <th>累计收益</th><th>年化</th><th>最大回撤</th><th>夏普</th><th>成交</th><th>曲线</th></tr></thead>
    <tbody>{rows}</tbody>
</table>
<div style="color:{TEXT_DIM}; font-size:11px; margin-top:8px;">
    共 {len(runs)} 次运行 · 归档目录 report/runs/ · 含 run.json（参数+指标）与 equity.csv（净值曲线）</div>
""", unsafe_allow_html=True)

st.divider()
sel = st.selectbox("查看净值曲线", [r["_dir"] for r in runs], index=0)
eq_file = ROOT / "report" / "runs" / sel / "equity.csv"
if eq_file.exists():
    import pandas as pd
    from web.charts import drawdown_chart, equity_chart

    eq = pd.read_csv(eq_file, parse_dates=["date"]).set_index("date")["equity"]
    c1, c2 = st.columns([2.2, 1])
    with c1:
        st.markdown('<div class="panel-title">EQUITY / 净值</div>', unsafe_allow_html=True)
        st.plotly_chart(equity_chart(eq, initial=float(eq.iloc[0])),
                        use_container_width=True, config={"displayModeBar": False})
    with c2:
        st.markdown('<div class="panel-title">DRAWDOWN / 水下</div>', unsafe_allow_html=True)
        st.plotly_chart(drawdown_chart(eq), use_container_width=True,
                        config={"displayModeBar": False})
else:
    st.info(f"该运行无净值曲线文件（{sel}，补录归档仅指标）。")

st.divider()
st.markdown(f"""
<div style="color:{TEXT_DIM}; font-size:12px;">
    运行明细 JSON：</div>
""", unsafe_allow_html=True)
meta_file = ROOT / "report" / "runs" / sel / "run.json"
if meta_file.exists():
    st.code(meta_file.read_text(encoding="utf-8"), language="json")
