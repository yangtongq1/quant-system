"""QMT 重发目标持仓（从 DB positions 读，实时行情限价，先卖后买）。

用途：run-paper 已算好目标持仓（在 DB positions 表）但因柜台禁交易废单后，
柜台恢复时秒级重发（无需 11 分钟重放）。

用法：python scripts/resend_positions.py [--dry-run]
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import sqlite3


def to_qmt_symbol(code: str) -> str:
    if code.startswith(("6", "9", "5")):
        return f"{code}.SH"
    if code.startswith(("0", "3", "1")):
        return f"{code}.SZ"
    return f"{code}.BJ"


def main() -> None:
    dry_run = "--dry-run" in sys.argv

    # 1. DB 目标持仓
    conn = sqlite3.connect(str(ROOT / "data" / "quant.db"))
    targets = dict(conn.execute(
        "SELECT code, volume FROM positions WHERE volume > 0"
    ).fetchall())
    conn.close()
    if not targets:
        print("[resend] DB 无目标持仓（先跑 run-paper）")
        return
    print(f"[resend] 目标持仓 {len(targets)} 只")

    # 2. 实时行情（对手价）
    from xtquant import xtdata
    symbols = [to_qmt_symbol(c) for c in targets]
    ticks = xtdata.get_full_tick(symbols) or {}
    quotes = {}
    for code, sym in zip(targets, symbols):
        d = ticks.get(sym) or {}
        last = d.get("lastPrice") or 0
        ask1 = (d.get("askPrice") or [0])[0]
        # 买入口径：卖一价（对手价），无盘口用最新价
        px = ask1 if ask1 and ask1 > 0 else last
        quotes[code] = float(px)
    missing = [c for c, p in quotes.items() if p <= 0]
    if missing:
        print(f"[resend] ⚠️ 无行情跳过: {missing}")
    targets = {c: v for c, v in targets.items() if quotes.get(c, 0) > 0}

    # 3. 当前持仓（QMT 实际）→ 差额单
    from execution.qmt_broker import QmtBroker
    broker = QmtBroker()
    if broker.dry_run:
        print(f"[resend] QMT 不可用：{broker.last_error}")
        return
    held = {}
    for p in broker.get_positions():
        code = str(getattr(p, "stock_code", "")).split(".")[0]
        vol = int(getattr(p, "volume", 0) or 0)
        if vol > 0:
            held[code] = vol

    orders = []
    all_codes = set(targets) | set(held)
    for code in sorted(all_codes):
        tgt = int(targets.get(code, 0))
        cur = int(held.get(code, 0))
        diff = tgt - cur
        if diff == 0:
            continue
        px = quotes.get(code, 0)
        if px <= 0 and diff > 0:
            print(f"[resend] ⚠️ {code} 无行情且需买入，跳过")
            continue
        # 限价：买入加 0.6% 缓冲、卖出减 0.6%，取整到分
        if diff > 0:
            limit = round(px * 1.006 + 0.005, 2)
            orders.append(("buy", code, diff, limit))
        else:
            limit = round(px * 0.994 - 0.005, 2) if px > 0 else 0.0
            orders.append(("sell", code, -diff, limit))

    sells = [o for o in orders if o[0] == "sell"]
    buys = [o for o in orders if o[0] == "buy"]
    print(f"[resend] 调仓单 {len(orders)} 笔（卖 {len(sells)} / 买 {len(buys)}）")

    if dry_run:
        for side, code, vol, px in sells + buys:
            print(f"  [DRY] {side:4s} {code} {vol} @ {px}")
        return

    # 4. 发单（先卖后买）
    ok, fail = 0, 0
    for side, code, vol, px in sells + buys:
        try:
            if side == "buy":
                oid = broker.buy(code, px, vol)
            else:
                oid = broker.sell(code, px, vol)
            st = next((o for o in broker.orders if o.get("order_id") == oid), {})
            status = st.get("status", "?")
            reason = st.get("reason", "")
            print(f"  {side:4s} {code} {vol} @ {px} → {status} {('(' + reason + ')') if reason else ''}")
            if status == "SUBMITTED":
                ok += 1
            else:
                fail += 1
            time.sleep(0.15)  # 限速，防柜台拒单
        except Exception as e:  # noqa: BLE001
            print(f"  {side:4s} {code} {vol} @ {px} → 异常 {type(e).__name__}: {str(e)[:80]}")
            fail += 1
    print(f"[resend] 完成：{ok} 笔委托成功 / {fail} 笔失败")

    # 5. 20 秒后回报成交
    print("[resend] 等待 20 秒查成交……")
    time.sleep(20)
    trades = list(broker.get_trades() or [])
    print(f"[resend] 本session成交 {len(trades)} 笔")
    for t in trades:
        print("  成交:", getattr(t, "stock_code", "?"), "vol", getattr(t, "traded_volume", "?"),
              "@", getattr(t, "traded_price", "?"))
    remain = list(broker.get_orders() or [])
    pending = [o for o in remain if o.order_status in (48, 49, 50, 55)]
    print(f"[resend] 未完结委托 {len(pending)} 笔（可撤单或等成交）")


if __name__ == "__main__":
    main()
