"""模拟盘实盘净值留痕（paper_equity）。

正式跑模拟盘拟合的核心度量：从 QMT 柜台读实际资产状态，逐日追加到
data/paper_equity.csv。自 2026-11-11（模拟盘正式起始日）起算。

多列口径（区分策略贡献 vs 用户操作）：
  total_asset    柜台总资产（东莞模拟柜台口径，事实源）
  cash           可用现金
  market_value   柜台总市值（含用户自有仓）
  strategy_mv    策略管理范围市值（管理范围 = orders∪positions 的 code）

用法：
  python scripts/paper_equity.py            # 今日留痕（幂等，重复跑只更新）
  python scripts/paper_equity.py --status   # 查看当前序列

调用时机：
  - run-paper 执行完后台账对齐后（main.py 执行链路尾自动调用）
  - scheduler 每日流程（step5，幂等）
"""
from __future__ import annotations

import argparse
import csv
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

PAPER_START = "2026-11-12"          # 100万仓位重建日（此前为 310万混合调试仓位，不计入）
CSV_PATH = ROOT / "data" / "paper_equity.csv"
FIELDS = ["date", "total_asset", "cash", "market_value", "strategy_mv", "source"]


def read_csv() -> list[dict]:
    if not CSV_PATH.exists():
        return []
    with open(CSV_PATH, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write_csv(rows: list[dict]) -> None:
    CSV_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CSV_PATH, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for r in rows:
            w.writerow(r)


def managed_codes() -> set[str]:
    """策略管理范围：orders 历史委托过的 ∪ 台账当前持仓的 code。"""
    db = ROOT / "data" / "quant.db"
    codes: set[str] = set()
    if not db.exists():
        return codes
    try:
        with sqlite3.connect(str(db)) as conn:
            for (c,) in conn.execute("SELECT DISTINCT code FROM orders"):
                codes.add(str(c))
            for (c,) in conn.execute(
                    "SELECT code FROM positions WHERE volume > 0"):
                codes.add(str(c))
    except Exception:  # noqa: BLE001
        pass
    return codes


def query_qmt() -> dict | None:
    """从 QMT 柜台查资产状态（连接失败返回 None）。

    返回 {total_asset, cash, market_value, strategy_mv}
    """
    try:
        from execution.qmt_broker import QmtBroker
        broker = QmtBroker(mode="paper")
        acc = broker.get_account()
        total = float(acc.get("total_value") or 0)
        cash = float(acc.get("available_cash") or 0)
        if total <= 0 and cash <= 0:
            return None
        managed = managed_codes()
        strategy_mv = 0.0
        market_value = 0.0
        for p in broker.get_positions():
            code = str(getattr(p, "stock_code", "") or "").split(".")[0]
            mv = float(getattr(p, "market_value", 0) or 0)
            market_value += mv
            if code in managed:
                strategy_mv += mv
        return {"total_asset": total, "cash": cash,
                "market_value": market_value, "strategy_mv": strategy_mv}
    except Exception:  # noqa: BLE001
        return None


def _fmt(x: float) -> str:
    return f"{x:.2f}"


def record(today: str | None = None) -> str:
    """今日留痕（幂等：同日已有则更新）。返回结果说明。"""
    today = today or datetime.now().strftime("%Y-%m-%d")
    if today < PAPER_START:
        return f"今日 {today} 早于正式起始日 {PAPER_START}，不留痕"

    q = query_qmt()
    if q is None:
        return "QMT 未连接，今日未留痕（下次 run 后自动补）"

    rows = [r for r in read_csv() if r["date"] >= PAPER_START]
    rows = [r for r in rows if r["date"] != today]  # 幂等：同日覆盖
    rows.append({"date": today, "total_asset": _fmt(q["total_asset"]),
                 "cash": _fmt(q["cash"]), "market_value": _fmt(q["market_value"]),
                 "strategy_mv": _fmt(q["strategy_mv"]), "source": "qmt"})
    rows.sort(key=lambda r: r["date"])
    write_csv(rows)
    return (f"已留痕 {today}: 总资产 {q['total_asset']:,.0f}"
            f"（现金 {q['cash']:,.0f} · 策略市值 {q['strategy_mv']:,.0f}）")


def status() -> str:
    rows = [r for r in read_csv() if r["date"] >= PAPER_START]
    if not rows:
        return f"无净值序列（正式起始日 {PAPER_START}）"
    last = rows[-1]
    lines = [f"模拟盘净值序列：{len(rows)} 天，{rows[0]['date']} ~ {last['date']}"]
    lines.append(f"  末日: 总资产 {float(last['total_asset']):,.0f} · "
                 f"现金 {float(last.get('cash') or 0):,.0f} · "
                 f"策略市值 {float(last.get('strategy_mv') or 0):,.0f}")
    # 策略市值口径的区间收益（剔除现金变动干扰）
    smv = [float(r["strategy_mv"]) for r in rows if r.get("strategy_mv")]
    if len(smv) >= 2 and smv[0] > 0:
        lines.append(f"  策略市值变化: {smv[-1] / smv[0] - 1:+.2%}"
                     f"（{smv[0]:,.0f} → {smv[-1]:,.0f}）")
    return "\n".join(lines)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--status", action="store_true")
    args = ap.parse_args()
    print(status() if args.status else record())
