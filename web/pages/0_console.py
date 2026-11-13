"""系统控制台：全功能模块操作台（不只看结果，还能操作系统）

模块：数据采集 / 回测 / 因子质检 / 风控压测 / 模拟盘 / 相关性监控
每个模块 = 参数表单 + 运行按钮 + 后台执行 + 实时日志 + 结果状态
"""
import subprocess
import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from web.theme import ACCENT, DOWN, TEXT_DIM, UP, inject_css
from web.i18n import t

st.set_page_config(page_title="系统控制台 · QUANT TERMINAL", layout="wide")
st.markdown(inject_css(), unsafe_allow_html=True)

st.markdown(f"""
<div class="page-title">◈ {t("系统控制台")} / SYSTEM CONSOLE</div>
<div style="color:{TEXT_DIM}; font-size:12px; margin-bottom:10px;">
    {t("系统操作台 · 数据采集 / 回测 / 因子 / 风控 / 执行 · 后台运行 + 实时日志")}</div>
""", unsafe_allow_html=True)


# ── 后台任务执行器（会话级状态 + 持久留痕 registry）──────────────
def start_task(key: str, cmd: list[str], label: str) -> None:
    """启动后台任务：记入 session_state，日志写 logs/console_<key>.log，持久留痕到 registry"""
    from scripts.runs_registry import start_run

    log_file = ROOT / "logs" / f"console_{key}.log"
    log_file.parent.mkdir(exist_ok=True)
    proc = subprocess.Popen(
        [sys.executable, *cmd],
        cwd=str(ROOT),
        stdout=open(log_file, "w", encoding="utf-8"),
        stderr=subprocess.STDOUT,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    rid = start_run(key, label, " ".join(cmd), str(log_file), proc.pid)
    st.session_state[f"task_{key}"] = {
        "pid": proc.pid, "label": label, "cmd": " ".join(cmd),
        "log": str(log_file), "done": False, "rid": rid,
    }


def task_status(key: str) -> dict | None:
    return st.session_state.get(f"task_{key}")


def poll_task(key: str) -> dict | None:
    """检查任务是否结束（通过 pid 是否存活），返回状态字典；结束时回写 registry 终态"""
    from scripts.runs_registry import finish_run

    t = st.session_state.get(f"task_{key}")
    if t is None:
        return None
    if not t.get("done"):
        import os
        try:
            import psutil
            alive = psutil.pid_exists(t["pid"])
        except ImportError:
            # tasklist 输出为 GBK，用 bytes 匹配防解码线程崩
            p = subprocess.run(["tasklist", "/FI", f"PID eq {t['pid']}"],
                               capture_output=True, timeout=10)
            alive = str(t["pid"]).encode() in p.stdout
        if not alive:
            t["done"] = True
            # 持久留痕：回写终态（日志尾部含 Traceback → failed，否则 done）
            if t.get("rid"):
                try:
                    tail = Path(t["log"]).read_text(encoding="utf-8",
                                                    errors="replace")[-4000:]
                    failed = "Traceback (most recent call last)" in tail
                except OSError:
                    failed = True
                finish_run(t["rid"], "failed" if failed else "done", None)
    return t


def show_task(key: str) -> None:
    """任务运行状态 + 日志尾部"""
    t = poll_task(key)
    if t is None:
        return
    state = "✅ 完成" if t["done"] else '<span class="live-dot green"></span>运行中'
    st.markdown(
        f"<div style='font-size:12px; color:{TEXT_DIM};'>"
        f"{t['label']} · {state} · <code>{t['cmd']}</code></div>",
        unsafe_allow_html=True)
    try:
        tail = Path(t["log"]).read_text(encoding="utf-8", errors="replace")[-1500:]
    except OSError:
        tail = "(无日志)"
    with st.expander("运行日志", expanded=t["done"]):
        st.code(tail, language="log" if tail else None)
    if t["done"]:
        if st.button("清除状态", key=f"clear_{key}"):
            del st.session_state[f"task_{key}"]
            st.rerun()


st.markdown('<div class="panel-title">DATA / 数据采集模块</div>', unsafe_allow_html=True)
d1, d2, d3 = st.columns(3)
with d1:
    st.markdown("**增量更新行情**（最近 N 日，幂等）", help="全池已入库标的的日线增量补采")
    days = st.number_input("回看天数", 5, 60, 10, key="fetch_days")
    if st.button("▶ 运行增量采集", use_container_width=True):
        start_task("fetch_recent",
                   ["scripts/scheduler.py", "--run-fetch-recent", str(days)],
                   f"增量采集（最近 {days} 日）")
with d2:
    st.markdown("**ETF 行情**（518880 黄金 / 513100 纳指）", help="从指定日期重采两只 ETF")
    etf_code = st.selectbox("ETF", ["518880 黄金ETF", "513100 纳指ETF"])
    if st.button("▶ 采集 ETF", use_container_width=True):
        start_task("fetch_etf", ["main.py", "fetch-etf", "--code", etf_code[:6],
                                 "--start", "20150101"], f"采集 {etf_code}")
with d3:
    st.markdown("**财报数据**（价值/质量因子源）", help="全市场财报增量入库")
    if st.button("▶ 采集财报", use_container_width=True):
        start_task("fetch_fund", ["scripts/fetch_fundamentals.py"], "财报批量入库")
show_task("fetch_recent")
show_task("fetch_etf")
show_task("fetch_fund")

st.divider()

st.markdown('<div class="panel-title">BACKTEST / 回测模块</div>', unsafe_allow_html=True)
b1, b2, b3, b4, b5 = st.columns(5)
with b1:
    lam = st.selectbox("风险档位 λ", ["0.1 稳健", "0.5 平衡", "0.9 进取"], index=1)
with b2:
    top_n = st.number_input("持股数 TopN", 10, 300, 100, step=10)
with b3:
    bt_start = st.text_input("开始日期", "20150101")
with b4:
    bt_end = st.text_input("结束日期", "20261105")
with b5:
    cash = st.number_input("初始资金（万）", 10, 10000, 100) * 10_000
if st.button("▶ 运行回测（全池 · 后台约 7-10 分钟）", use_container_width=True, type="primary"):
    start_task("backtest",
               ["main.py", "backtest", "--strategy", "cross_asset",
                "--lam", lam.split()[0], "--top-n", str(int(top_n)),
                "--start", bt_start, "--end", bt_end, "--cash", str(int(cash))],
               f"回测 λ={lam} TopN={top_n}")
show_task("backtest")

st.divider()

st.markdown('<div class="panel-title">FACTORS / 因子质检模块</div>', unsafe_allow_html=True)
f1, f2 = st.columns([1, 2])
with f1:
    qa_n = st.number_input("抽样池大小", 100, 3000, 800, step=100,
                           help="按成交额取流动性最好的 N 只（全池太慢）")
    if st.button("▶ 全池 IC 质检", use_container_width=True):
        start_task("factors_qa", ["scripts/factor_ic_fullpool.py", "--top-n", str(int(qa_n))],
                   f"因子 IC 质检（top {qa_n}）")
with f2:
    qa_csv = ROOT / "report" / "qa" / "fullpool_ic.csv"
    if qa_csv.exists():
        import pandas as pd
        df = pd.read_csv(qa_csv)
        if len(df):
            rows = "".join(
                f"<tr><td>{r['factor']}</td>"
                f"<td class='{'up' if (r['ic_mean'] or 0) >= 0 else 'down'}'>{r['ic_mean']:+.4f}</td>"
                f"<td>{r.get('icir', '-')}</td><td>{r.get('ic_win_rate', '-')}</td></tr>"
                for _, r in df.iterrows())
            st.markdown(f"""
            <table class="data-table">
            <thead><tr><th>因子</th><th>IC 均值</th><th>ICIR</th><th>胜率</th></tr></thead>
            <tbody>{rows}</tbody></table>
            <div style="color:{TEXT_DIM}; font-size:11px;">最近一次质检结果 · report/qa/fullpool_ic.csv</div>
            """, unsafe_allow_html=True)
    else:
        st.info("尚无质检结果，运行后在此显示。")
show_task("factors_qa")

st.divider()

st.markdown('<div class="panel-title">RISK / 风控模块</div>', unsafe_allow_html=True)
r1, r2 = st.columns(2)
with r1:
    st.markdown("**压力测试**（历史极端场景回放）")
    if st.button("▶ 运行压力测试", use_container_width=True):
        start_task("stress", ["main.py", "stress"], "压力测试")
with r2:
    st.markdown("**相关性监控**（分散失效检测）")
    if st.button("▶ 运行相关性监控", use_container_width=True):
        start_task("monitor", ["main.py", "monitor"], "相关性监控")
show_task("stress")
show_task("monitor")

st.divider()

st.markdown('<div class="panel-title">EXECUTION / 执行模块（模拟盘）</div>', unsafe_allow_html=True)
e1, e2, e3 = st.columns([1, 1, 2])
with e1:
    p_lam = st.selectbox("λ 档位", ["0.1", "0.5", "0.9"], index=1, key="paper_lam")
with e2:
    p_top = st.number_input("持股数", 10, 300, 30, key="paper_top")
with e3:
    st.markdown("**生成模拟盘信号**（重放策略到最新日 → 目标持仓 → 差额订单）")
    if st.button("▶ 运行模拟盘信号", use_container_width=True, type="primary"):
        start_task("run_paper", ["main.py", "run-paper", "--lam", p_lam, "--top-n", str(int(p_top))],
                   f"模拟盘 λ={p_lam} TopN={p_top}")
show_task("run_paper")

# SuperMind / QMT 连接状态卡（同步诊断，秒级）
sm_c1, sm_c2 = st.columns([2, 1])
with sm_c1:
    st.markdown("**SuperMind 仿真通道**（真实委托需客户端在线 + 资金账号）")
    if st.button("▶ 诊断 SuperMind 连接", use_container_width=True):
        try:
            from execution.supermind_broker import SuperMindBroker
            b = SuperMindBroker()
            st_status = b.status()
            if st_status["mode"] == "LIVE":
                acct = b.get_account()
                pos_n = len(b.get_positions())
                st.success(f"已连接真实仿真账户 {st_status['account']}："
                           f"总资产 {acct.get('total_value', '?')} · 持仓 {pos_n} 只")
            else:
                st.warning(f"DRY_RUN 模式：{st_status['last_error']}")
                st.caption("修复：① 装客户端 zjcmpp.hexin.com.cn（下载 THS_Qstudio_Setup_Mfjy.exe）"
                           "② 同花顺账号登录并创建仿真账户 ③ 资金账号写入 .env 的 SUPERMIND_ACCOUNT")
        except Exception as e:  # noqa: BLE001
            st.error(f"诊断异常：{e}")
with sm_c2:
    if st.button("▶ 模拟盘走 SuperMind", use_container_width=True,
                 help="需客户端在线且 .env 配置 SUPERMIND_ACCOUNT，否则自动回退本地 PaperBroker"):
        start_task("run_paper_sm",
                   ["main.py", "run-paper", "--supermind", "--lam", p_lam,
                    "--top-n", str(int(p_top))],
                   f"模拟盘（SuperMind）λ={p_lam} TopN={p_top}")
show_task("run_paper_sm")

# QMT / miniQMT 通道（推荐路线）
q_c1, q_c2 = st.columns([2, 1])
with q_c1:
    st.markdown("**QMT / miniQMT 通道**（券商开通 · 软件 free · xtquant 官方 SDK）")
    if st.button("▶ 诊断 QMT 连接", use_container_width=True):
        try:
            from execution.qmt_broker import QmtBroker
            b = QmtBroker()
            stq = b.status()
            if stq["mode"] == "LIVE":
                acct = b.get_account()
                pos_n = len(b.get_positions())
                st.success(f"已连接 QMT 账户 {stq['account']}："
                           f"总资产 {acct.get('total_value', '?')} · 持仓 {pos_n} 只")
            else:
                st.warning(f"DRY_RUN 模式：{stq['last_error']}")
                st.caption("开通：① 券商开 QMT 权限（国金/华西/方正/华宝等 10 万日均即可）"
                           "② 装 QMT 客户端登录并启动 miniQMT "
                           "③ .env 配 QMT_ACCOUNT / QMT_PATH")
        except Exception as e:  # noqa: BLE001
            st.error(f"诊断异常：{e}")
with q_c2:
    if st.button("▶ 模拟盘走 QMT", use_container_width=True,
                 help="需 miniQMT 运行且 .env 配置 QMT_ACCOUNT，否则自动回退本地 PaperBroker"):
        start_task("run_paper_qmt",
                   ["main.py", "run-paper", "--qmt", "--lam", p_lam,
                    "--top-n", str(int(p_top))],
                   f"模拟盘（QMT）λ={p_lam} TopN={p_top}")
show_task("run_paper_qmt")

st.divider()
st.markdown('<div class="panel-title">RECENT RUNS / 最近运行留痕</div>', unsafe_allow_html=True)
try:
    from scripts.runs_registry import load_runs
    recent = load_runs(limit=8)
    if recent:
        badge = {
            "done": '<span style="color:#4ADE80;">✓ done</span>',
            "failed": '<span style="color:#F87171;">✗ failed</span>',
            "running": '<span class="live-dot green"></span>running',
            "aborted": '<span style="color:#FBBF24;">− aborted</span>',
        }
        trs = []
        for r in recent:
            dur = "-" if r.get("duration_s") is None else f"{r['duration_s']:.0f}s"
            trs.append(
                f"<tr><td>{r['ts_start']}</td>"
                f"<td>{r.get('label', r.get('key', '-'))}</td>"
                f"<td>{badge.get(r.get('status'), r.get('status'))}</td>"
                f"<td>{dur}</td>"
                f"<td class='mono' style='font-size:11px;'>{(r.get('cmd') or '')[:80]}</td></tr>"
            )
        st.markdown(f"""
        <table class="data-table">
            <thead><tr><th>开始时间</th><th>任务</th><th>状态</th><th>耗时</th><th>命令</th></tr></thead>
            <tbody>{''.join(trs)}</tbody>
        </table>
        <div style="color:{TEXT_DIM}; font-size:11px; margin-top:6px;">
            全部留痕见「运行中心」页 · 持久记录 data/console_runs.json</div>
        """, unsafe_allow_html=True)
    else:
        st.info("暂无运行留痕。点击上方任意按钮运行后自动记录。")
except Exception as e:  # noqa: BLE001
    st.warning(f"留痕读取异常：{e}")

st.divider()
st.markdown(f"""
<div style="color:{TEXT_DIM}; font-size:11px;">
    所有任务后台执行（不阻塞看板）· 日志在 logs/console_*.log ·
    回测结果自动归档 report/runs/ · 调度器每日 15:30 自动跑全流程</div>
""", unsafe_allow_html=True)

# 运行中任务自动 5 秒刷新（仅当存在未完成任务时触发一次 rerun）
has_running = any(
    (t := st.session_state.get(f"task_{k}")) and not t.get("done")
    for k in ["fetch_recent", "fetch_etf", "fetch_fund", "backtest",
              "factors_qa", "stress", "monitor", "run_paper", "run_paper_sm",
              "run_paper_qmt"]
)
if has_running:
    st.empty()  # 占位避免空容器警告
    import time
    time.sleep(5)
    st.rerun()
