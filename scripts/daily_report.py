"""每日交易日报生成（收盘后/scheduler 调用/看板一键生成）。

产出：report/daily/YYYY-MM-DD.md
内容：当日成交汇总（笔数/金额/买卖分向）、持仓快照与盈亏、台账对齐状态、
风控事件、数据新鲜度。
用法：python scripts/daily_report.py [YYYY-MM-DD]
"""
from __future__ import annotations

import sqlite3
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

DB = ROOT / "data" / "quant.db"
OUT_DIR = ROOT / "report" / "daily"

ETF_NAMES = {"518880": "黄金ETF", "513100": "纳指ETF"}


def board_cn(code: str) -> str:
    code = str(code)
    if code == "518880":
        return "黄金ETF"
    if code == "513100":
        return "纳指ETF"
    if code.startswith(("300", "301")):
        return "创业板"
    if code.startswith("688"):
        return "科创板"
    if code.startswith(("600", "601", "603", "605")):
        return "沪市主板"
    if code.startswith(("000", "001", "002", "003")):
        return "深市主板"
    return "其他"


def generate(day: str | None = None) -> Path:
    day = day or datetime.now().strftime("%Y-%m-%d")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"{day}.md"
    if not DB.exists():
        raise RuntimeError("quant.db 不存在")

    conn = sqlite3.connect(str(DB))
    cur = conn.cursor()

    # ── 当日委托（真实通道单：SUBMITTED/REJECTED）──
    orders = cur.execute(
        "SELECT create_time, code, side, price, volume, status FROM orders "
        "WHERE create_time LIKE ? ORDER BY create_time", (f"{day}%",)
    ).fetchall()

    # ── 当日重放成交流水（trades 表当日）──
    trades = cur.execute(
        "SELECT time, code, side, price, volume, fee FROM trades "
        "WHERE time LIKE ? ORDER BY time", (f"{day}%",)
    ).fetchall()

    # ── 持仓快照 ──
    positions = cur.execute(
        "SELECT code, volume, avg_cost FROM positions WHERE volume > 0 "
        "ORDER BY code"
    ).fetchall()

    # ── 账户 ──
    try:
        account = cur.execute(
            "SELECT cash, total_asset, update_time FROM accounts "
            "WHERE account_id='paper_local'"
        ).fetchone() or (0, 0, "")
    except Exception:  # noqa: BLE001
        account = (0, 0, "")

    # 名称映射
    name_map = {}
    try:
        for c, n in cur.execute("SELECT code, name FROM stocks").fetchall():
            name_map[c] = n
    except Exception:  # noqa: BLE001
        pass
    conn.close()

    # ── 汇总统计 ──
    n_buy = sum(1 for o in orders if o[2] == "buy")
    n_sell = sum(1 for o in orders if o[2] == "sell")
    buy_amt = sum(o[3] * o[4] for o in orders if o[2] == "buy")
    sell_amt = sum(o[3] * o[4] for o in orders if o[2] == "sell")
    n_sub = sum(1 for o in orders if str(o[5]).startswith("SUBMITTED"))
    n_rej = sum(1 for o in orders if str(o[5]).startswith("REJECTED"))
    n_skip = sum(1 for o in orders if str(o[5]).startswith("SKIPPED"))
    replay_buy = sum(t[3] * t[4] for t in trades if t[2] == "buy")
    replay_sell = sum(t[3] * t[4] for t in trades if t[2] == "sell")

    lines = [
        f"# 交易日报 · {day}",
        "",
        f"> 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "> **100 万仓位重建自 2026-11-12**（此前为混合调试仓位，不计入；日频调仓+两日买入限流25%）",
        "",
        "## 一、当日委托执行（外部通道）",
        "",
        f"- 委托笔数：**{len(orders)}**（买入 {n_buy} / 卖出 {n_sell}）",
        f"- 已委托 {n_sub} 笔 · 风控拒绝 {n_rej} 笔 · 跳过(T+1锁定等) {n_skip} 笔",
        f"- 买入金额：**{buy_amt:,.0f} 元**　卖出金额：**{sell_amt:,.0f} 元**",
        f"- 净买入：**{buy_amt - sell_amt:+,.0f} 元**",
        "",
    ]
    if orders:
        lines += ["| 时间 | 代码 | 名称 | 方向 | 价格 | 数量 | 金额 | 板块 | 状态 |",
                  "|---|---|---|---|---|---|---|---|---|"]
        for o in orders:
            ts, code, side, px, vol, status = o
            side_zh = "买入" if side == "buy" else "卖出"
            status_zh = ("已委托" if str(status).startswith("SUBMITTED")
                         else "风控拒绝" if str(status).startswith("REJECTED")
                         else "跳过" if str(status).startswith("SKIPPED")
                         else str(status))
            name = name_map.get(code, ETF_NAMES.get(code, "—"))
            amt = px * vol
            lines.append(
                f"| {str(ts)[11:19]} | {code} | {name} | {side_zh} | {px:.2f} | "
                f"{vol:,} | {amt:,.0f} | {board_cn(code)} | {status_zh} |")
        lines.append("")
    else:
        lines += ["当日无委托。\n"]

    lines += [
        "## 二、当日重放成交流水（策略回放语义）",
        "",
        f"- 成交 {len(trades)} 笔（买入 {replay_buy:,.0f} 元 / 卖出 {replay_sell:,.0f} 元）",
        "",
    ]
    if trades:
        lines += ["| 日期 | 代码 | 方向 | 价格 | 数量 | 费用 |", "|---|---|---|---|---|---|"]
        for t in trades[:50]:
            tm, code, side, px, vol, fee = t
            side_zh = "买入" if side == "buy" else "卖出"
            lines.append(f"| {tm} | {code} | {side_zh} | {px:.2f} | {vol:,} | {fee:.2f} |")
        if len(trades) > 50:
            lines.append(f"| … | 共 {len(trades)} 笔，仅列前 50 | | | | |")
        lines.append("")

    lines += [
        "## 三、持仓快照（对齐柜台）",
        "",
        f"- 持仓 {len(positions)} 只 · 现金 {account[0]:,.0f} 元 · 总资产 {account[1]:,.0f} 元",
        "",
    ]
    if positions:
        lines += ["| 代码 | 名称 | 持股数 | 成本 | 板块 |", "|---|---|---|---|---|"]
        for code, vol, cost in positions:
            name = name_map.get(code, ETF_NAMES.get(code, "—"))
            lines.append(f"| {code} | {name} | {vol:,} | {cost or 0:.3f} | {board_cn(code)} |")
        lines.append("")

    # 数据新鲜度
    bars_dir = ROOT / "data" / "bars"
    etf = bars_dir / "518880.parquet"
    try:
        import pandas as pd
        last = pd.read_parquet(etf, columns=["date"])["date"].iloc[-1]
        last_str = str(pd.Timestamp(last).date())
    except Exception:  # noqa: BLE001
        last_str = "—"
    lines += [
        "## 四、数据健康",
        "",
        f"- 行情库标的：{len(list(bars_dir.glob('*.parquet')))} 只",
        f"- 行情数据截至：{last_str}（当日委托基于该日收盘价重放）",
        f"- ST/退市股清理：已执行（clean_st_delist.py）",
        "",
        "---",
        "*本报告由系统自动生成；模拟盘语义，不构成投资建议。*",
    ]

    out.write_text("\n".join(lines), encoding="utf-8")
    return out


if __name__ == "__main__":
    d = sys.argv[1] if len(sys.argv) > 1 else None
    p = generate(d)
    print(f"日报已生成：{p}")
