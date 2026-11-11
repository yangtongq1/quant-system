"""一键操作台：常用任务整合按钮（每键一个任务，跑完即显结果）。

一键：增量拉取K线 · 盈亏分析 · 交易日涨跌幅 · ST/退市清理 · 数据健康检查
"""
import sqlite3
import subprocess
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from web.i18n import t
from web.theme import ACCENT, TEXT_DIM, UP, DOWN, inject_css, kpi_card, kpi_grid

st.set_page_config(page_title="一键操作台 · QUANT TERMINAL", layout="wide")
st.markdown(inject_css(), unsafe_allow_html=True)

st.markdown(f"""
<div class="page-title">◈ {t("一键操作台")} / ONE-CLICK CONSOLE</div>
<div style="color:{TEXT_DIM}; font-size:12px; margin-bottom:10px;">
    {t("点击上方按钮执行对应任务")} · 整合常用操作</div>
""", unsafe_allow_html=True)

ETF_NAMES = {"518880": "黄金ETF", "513100": "纳指ETF"}


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


# ════════ 1. 一键增量拉取最新 K 线 ════════
st.markdown(f'<div class="panel-title">① {t("一键拉取最新K线")} / FETCH K-LINES</div>',
            unsafe_allow_html=True)
c = st.columns([1, 3])
with c[0]:
    if st.button(f"📥 {t('一键拉取最新K线')}", use_container_width=True,
                  help="增量拉取全部标的最近 10 日日线（幂等，约 70 分钟，后台运行）"):
        log_file = ROOT / "logs" / "fetch_recent.log"
        proc = subprocess.Popen(
            [sys.executable, "-c",
             "import sys; sys.path.insert(0, 'scripts'); "
             "from scheduler import step_fetch_recent; step_fetch_recent(10)"],
            cwd=str(ROOT), stdout=open(log_file, "wb"), stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS,
        )
        st.success(f"后台已启动（PID {proc.pid}），日志：logs/fetch_recent.log，约 70 分钟完成")
with c[1]:
    st.caption("增量补齐最近 10 日日线；与 adj_factor 修复后的合并逻辑一致（新行因子 ffill 继承）")# ════════ 2. 盈亏分析 ════════
st.markdown(f'<div class="panel-title">② {t("盈亏分析")} / P&L</div>',
            unsafe_allow_html=True)
if st.button(f"📊 {t('盈亏分析')}（当前持仓 vs 成本）", use_container_width=True):
    db = ROOT / "data" / "quant.db"
    names = load_names()
    with sqlite3.connect(str(db)) as conn:
        try:
            pos = pd.read_sql(
                "SELECT code, volume, avg_cost FROM positions WHERE volume > 0", conn)
        except Exception:  # noqa: BLE001
            pos = pd.DataFrame()
    if pos.empty:
        st.info(t("暂无数据"))
    else:
        rows = []
        for _, r in pos.iterrows():
            code = str(r["code"])
            p = ROOT / "data" / "bars" / f"{code}.parquet"
            if not p.exists():
                continue
            try:
                df = pd.read_parquet(p, columns=["close"])
                last = float(df["close"].iloc[-1])
            except Exception:  # noqa: BLE001
                continue
            cost = float(r["avg_cost"] or 0)
            if cost <= 0:
                continue  # 无成本记录（老数据）跳过
            vol = int(r["volume"])
            pnl = (last - cost) * vol
            pnl_pct = last / cost - 1
            rows.append({
                "代码": code, "名称": names.get(code, ETF_NAMES.get(code, "—")),
                "持股": vol, "成本": round(cost, 3), "现价": round(last, 3),
                "浮动盈亏(元)": round(pnl, 0),
                "收益率": f"{pnl_pct:+.2%}",
            })
        if rows:
            pdf = pd.DataFrame(rows).sort_values("浮动盈亏(元)", ascending=False)
            total_pnl = pdf["浮动盈亏(元)"].sum()
            n_win = int((pdf["浮动盈亏(元)"] > 0).sum())
            n_lose = len(pdf) - n_win
            wl = n_win / max(n_lose, 1)
            st.markdown(kpi_grid([
                kpi_card("持仓标的", f"{len(pdf)}", "含成本记录"),
                kpi_card("浮动盈亏", f"{total_pnl:+,.0f}", "元",
                         cls="kpi-up" if total_pnl >= 0 else "kpi-down"),
                kpi_card("盈利/亏损", f"{n_win} / {n_lose}", "只"),
                kpi_card("盈亏比", f"{wl:.2f}", "win/lose"),
            ]), unsafe_allow_html=True)
            st.dataframe(pdf, use_container_width=True, hide_index=True, on_select="ignore")
        else:
            st.info("持仓无成本记录（今日 run 后柜台成本已入台账，明日有效）")

# ════════ 3. 交易日涨跌幅 ════════
st.markdown(f'<div class="panel-title">③ {t("交易日涨跌幅")} / DAILY CHANGE</div>',
            unsafe_allow_html=True)
if st.button(f"📈 {t('交易日涨跌幅')}（持仓 + ETF）", use_container_width=True):
    db = ROOT / "data" / "quant.db"
    names = load_names()
    with sqlite3.connect(str(db)) as conn:
        try:
            pos = pd.read_sql(
                "SELECT code, volume FROM positions WHERE volume > 0", conn)
        except Exception:  # noqa: BLE001
            pos = pd.DataFrame()
    rows = []
    for code in pos["code"].astype(str).tolist() + ["518880", "513100"]:
        code = str(code)
        p = ROOT / "data" / "bars" / f"{code}.parquet"
        if not p.exists() or any(r["代码"] == code for r in rows):
            continue
        try:
            df = pd.read_parquet(p, columns=["date", "close"])
            if len(df) < 2:
                continue
            chg = df["close"].iloc[-1] / df["close"].iloc[-2] - 1
            chg5 = df["close"].iloc[-1] / df["close"].iloc[-6] - 1 if len(df) >= 6 else None
            rows.append({
                "代码": code, "名称": names.get(code, ETF_NAMES.get(code, "—")),
                "收盘": round(float(df["close"].iloc[-1]), 3),
                "日期": str(pd.Timestamp(df["date"].iloc[-1]).date()),
                "当日涨跌": f"{chg:+.2%}",
                "5日涨跌": f"{chg5:+.2%}" if chg5 is not None else "—",
            })
        except Exception:  # noqa: BLE001
            continue
    if rows:
        cdf = pd.DataFrame(rows).sort_values("当日涨跌", ascending=False)
        up_n = sum(1 for r in rows if r["当日涨跌"].startswith("+"))
        st.markdown(kpi_grid([
            kpi_card("上涨/下跌", f"{up_n} / {len(rows) - up_n}", "只",
                     cls="kpi-up" if up_n * 2 >= len(rows) else "kpi-down"),
            kpi_card("最大涨幅", cdf.iloc[0]["当日涨跌"], cdf.iloc[0]["名称"], cls="kpi-up"),
            kpi_card("最大跌幅", cdf.iloc[-1]["当日涨跌"], cdf.iloc[-1]["名称"], cls="kpi-down"),
        ]), unsafe_allow_html=True)
        st.dataframe(cdf, use_container_width=True, hide_index=True, on_select="ignore")
    else:
        st.info(t("暂无数据"))

# ════════ 4. ST/退市清理 + 数据健康 ════════
st.markdown(f'<div class="panel-title">④ {t("数据健康检查")} / DATA HEALTH</div>',
            unsafe_allow_html=True)
c = st.columns(2)
with c[0]:
    if st.button(f"🧹 清理 ST/退市股日线", use_container_width=True,
                  help="按 stocks 表 is_st/status 判定，删除对应 parquet（策略池自动缩小）"):
        sys.path.insert(0, str(ROOT / "scripts"))
        from clean_st_delist import run
        r = run()
        msg = (f"删除 ST {r['removed_st']} + 退市 {r['removed_delist']}，"
               f"库剩 {r['remaining']} 只")
        st.success(msg)
with c[1]:
    if st.button(f"🩺 {t('数据健康检查')}", use_container_width=True,
                  help="因子塌陷/日期断档/负价扫描"):
        bars_dir = ROOT / "data" / "bars"
        files = sorted(bars_dir.glob("*.parquet"))
        n_collapse = n_gap = n_neg = 0
        sample_collapse = []
        for p in files[:800]:
            try:
                df = pd.read_parquet(p, columns=["date", "close", "adj_factor"])
                af = pd.to_numeric(df["adj_factor"], errors="coerce")
                if len(af) >= 2 and af.iloc[-1] == 1.0 and af.iloc[-2] != 1.0 \
                        and abs(af.iloc[-2] - 1.0) / max(af.iloc[-2], 1e-9) > 0.01:
                    n_collapse += 1
                    if len(sample_collapse) < 5:
                        sample_collapse.append(p.stem)
                dates = pd.to_datetime(df["date"])
                gaps = dates.diff().dt.days
                if (gaps > 15).any():
                    n_gap += 1
                if (df["close"] <= 0).any():
                    n_neg += 1
            except Exception:  # noqa: BLE001
                continue
        st.markdown(kpi_grid([
            kpi_card("扫描标的", f"{min(len(files), 800)}", f"共 {len(files)} 只"),
            kpi_card("因子塌陷", f"{n_collapse}", "末行=1 且前值≠1",
                     cls="kpi-down" if n_collapse else "kpi-up"),
            kpi_card("日期断档>15天", f"{n_gap}", "长期停牌类"),
            kpi_card("负价格", f"{n_neg}", "异常数据", cls="kpi-down" if n_neg else "kpi-up"),
        ]), unsafe_allow_html=True)
        if sample_collapse:
            st.warning(f"塌陷样本：{sample_collapse}（跑 clean_st_delist 后重新增量可修复）")

st.divider()
st.caption(f"任务以当前 {t('控制台')} 运行用户执行；长任务（增量K线）后台运行不阻塞看板。")
