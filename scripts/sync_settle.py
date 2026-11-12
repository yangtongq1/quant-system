"""结算同步（sync-settle）：东莞柜台批次撮合后的对账自动化。

背景（2026-11-12 踩坑）：东莞模拟柜台批次撮合延迟 30-50 分钟——
run-paper 尾部的 get_positions() 拿到的是撮合中间态，导致：
  ① 台账被污染（已清仓的 ST 股旧持仓被写回）
  ② 订单状态停留在 SUBMITTED 不回写（成交/部成/已撤不落库）
  ③ 净值留痕用了中间态资产（当日数字失真）
  ④ 同日重复 run 会重复委托（柜台还在撮合旧单，差额基准不含未成交量）

用法：
  python scripts/sync_settle.py            # 执行同步（幂等，可反复跑）
  python main.py sync-settle               # 同上（CLI 入口）

做三件事（柜台 = 事实源）：
  1. 台账对齐：柜台管理范围内终态持仓 → positions 表（清零/修正/新增）
  2. 订单回写：柜台委托状态映射回 orders 表（code+side+当日匹配）
  3. 净值重留痕：柜台终态资产 → paper_equity.csv（幂等覆盖当日）

建议时机：收盘后 / 次日 run-paper 前 / 撮合完成后任意时刻。
"""
from __future__ import annotations

import sqlite3
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# 柜台订单状态 → DB orders.status 语义映射
# 50 已报 / 54 已撤 / 55 部成 / 56 已成 / 57 部成待撤 / 58 已撤
_QMT_STATUS_MAP = {
    50: "SUBMITTED", 54: "CANCELLED", 55: "PARTIAL_FILLED",
    56: "FILLED", 57: "PARTIAL_CANCELLED", 58: "CANCELLED",
}


def _managed_codes(conn: sqlite3.Connection) -> set[str]:
    """策略管理范围 = orders 历史委托 ∪ 台账当前持仓的 code。"""
    codes = {str(r[0]) for r in conn.execute("SELECT DISTINCT code FROM orders") if r[0]}
    codes |= {str(r[0]) for r in conn.execute(
        "SELECT code FROM positions WHERE volume > 0") if r[0]}
    return codes


def sync(verbose: bool = True) -> dict:
    """执行结算同步。返回摘要 dict（对齐明细，供 UI/测试消费）。"""
    from execution.qmt_broker import QmtBroker
    from execution.paper_engine import _pos_fields

    broker = QmtBroker(mode="paper")
    conn = sqlite3.connect(str(ROOT / "data" / "quant.db"))
    cur = conn.cursor()
    summary: dict = {"removed": [], "changed": {}, "added": [],
                     "orders_updated": [], "equity": ""}

    # ── 1. 台账对齐：柜台管理范围内终态持仓 → positions ──
    managed = _managed_codes(cur)
    ch_pos: dict[str, tuple[int, float]] = {}
    for p in broker.get_positions():
        code, vol, _can, cost = _pos_fields(p)
        if vol > 0 and code in managed:
            ch_pos[code] = (int(vol), float(cost))

    cur.execute("SELECT code, volume FROM positions")
    before = {r[0]: r[1] for r in cur.fetchall()}
    cur.execute("DELETE FROM positions")
    for code, (vol, cost) in ch_pos.items():
        cur.execute(
            "INSERT OR REPLACE INTO positions (code, volume, avg_cost, market_value) "
            "VALUES (?, ?, ?, 0)", (code, vol, cost))
    conn.commit()

    summary["removed"] = sorted(c for c in before if c not in ch_pos)
    summary["changed"] = {c: (before[c], ch_pos[c][0])
                          for c in before if c in ch_pos and before[c] != ch_pos[c][0]}
    summary["added"] = sorted(c for c in ch_pos if c not in before)

    # ── 2. 订单回写：柜台委托状态（quant-system 今日）→ orders ──
    today_start = datetime.now().replace(
        hour=0, minute=0, second=0, microsecond=0).timestamp()
    qmt_orders = []
    for o in broker.get_orders():
        if getattr(o, "order_remark", "") != "quant-system":
            continue
        if float(getattr(o, "order_time", 0) or 0) < today_start:
            continue
        qmt_orders.append({
            "code": str(o.stock_code).split(".")[0],
            "side": "buy" if o.order_type == 23 else "sell",
            "t": datetime.fromtimestamp(float(o.order_time)),
            "vol": int(o.order_volume),
            "traded": int(o.traded_volume),
            "st": _QMT_STATUS_MAP.get(int(o.order_status), str(o.order_status)),
        })

    cur.execute(
        "SELECT code, side, volume, status, create_time FROM orders "
        "WHERE date(create_time)=date('now','localtime') AND status NOT LIKE 'SKIPPED%'")
    db_orders = cur.fetchall()
    n_updated = 0
    for code, side, vol, status, ct in db_orders:
        ct_dt = datetime.fromisoformat(ct)
        # 柜台委托号会复用 → 按 code+side+5 分钟窗口匹配
        cands = [q for q in qmt_orders
                 if q["code"] == code and q["side"] == side
                 and abs((q["t"] - ct_dt).total_seconds()) < 300]
        if not cands:
            continue
        q = cands[0]
        new_status = q["st"]
        if q["st"] == "PARTIAL_FILLED":
            new_status = f"PARTIAL_FILLED({q['traded']}/{q['vol']})"
        if new_status != status:
            cur.execute(
                "UPDATE orders SET status=?, update_time=? "
                "WHERE code=? AND side=? AND create_time=?",
                (new_status, datetime.now().isoformat(timespec="seconds"),
                 code, side, ct))
            n_updated += 1
            summary["orders_updated"].append(
                {"code": code, "side": side, "old": status, "new": new_status})
    conn.commit()

    # ── 3. 净值重留痕（柜台终态） ──
    try:
        from scripts.paper_equity import record
        summary["equity"] = record()
    except Exception as e:  # noqa: BLE001
        summary["equity"] = f"净值留痕失败：{type(e).__name__}: {e}"

    if verbose:
        print("=" * 56)
        print("结算同步（sync-settle）· 柜台 = 事实源")
        print("=" * 56)
        print(f"  管理范围     : {len(managed)} 只")
        print(f"  台账对齐     : 清除 {len(summary['removed'])} · "
              f"修正 {len(summary['changed'])} · 新增 {len(summary['added'])}")
        for c in summary["removed"]:
            print(f"    - 清除 {c}（柜台已无持仓）")
        for c, (a, b) in summary["changed"].items():
            print(f"    ~ 修正 {c}: {a} → {b}")
        for c in summary["added"]:
            print(f"    + 新增 {c}")
        print(f"  订单回写     : {n_updated} 笔状态更新")
        for u in summary["orders_updated"]:
            print(f"    {u['code']} {u['side']}: {u['old']} → {u['new']}")
        print(f"  净值留痕     : {summary['equity']}")
        print("=" * 56)
    return summary


if __name__ == "__main__":
    sync()
