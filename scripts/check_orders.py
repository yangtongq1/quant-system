"""核查 QMT 委托成交状态（run 后复盘用）。

用法：python scripts/check_orders.py [分钟前]
  默认查本 session 全部委托；传分钟数只看最近 N 分钟的委托。

输出：每笔委托的柜台状态（已成/部成/已报/废单），汇总成交量/成交额。
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from execution.qmt_broker import QmtBroker  # noqa: E402

STATUS = {
    48: "未报", 49: "待报", 50: "已报", 51: "已报待撤", 52: "部成待撤",
    53: "部成", 54: "已撤", 55: "部成", 56: "已成", 57: "废单",
}


def main() -> None:
    minutes = float(sys.argv[1]) if len(sys.argv) > 1 else 0
    b = QmtBroker()
    if b.dry_run:
        print(f"[check] QMT 不可用：{b.last_error}")
        return
    orders = b.get_orders()
    now = datetime.now()
    shown = 0
    total_traded = 0.0
    n_filled = n_partial = n_pending = n_dead = 0
    print(f"=== QMT 委托状态（本 session {len(orders)} 笔"
          f"{'，最近 ' + str(minutes) + ' 分钟' if minutes else ''}）===")
    for o in orders:
        code = str(getattr(o, "stock_code", "?"))
        otype = getattr(o, "order_type", 0)
        side = "买" if otype == 23 else "卖"
        vol = int(getattr(o, "order_volume", 0) or 0)
        trd = int(getattr(o, "traded_volume", 0) or 0)
        status = STATUS.get(getattr(o, "order_status", 0), "?")
        # 时间过滤（order_time 是 epoch 秒）
        t = getattr(o, "order_time", 0)
        if minutes and t:
            if datetime.now() - datetime.fromtimestamp(t) > timedelta(minutes=minutes):
                continue
        price = float(getattr(o, "price", 0) or 0)
        total_traded += trd * price if trd else 0
        if status == "已成":
            n_filled += 1
        elif status in ("部成", "部成待撤"):
            n_partial += 1
        elif status in ("废单",):
            n_dead += 1
        else:
            n_pending += 1
        print(f"  {code} {side} {vol}股 成交{trd} @{price:.2f} → {status}")
        shown += 1
    print("-" * 50)
    print(f"合计 {shown} 笔：已成 {n_filled} / 部成 {n_partial} / "
          f"在途 {n_pending} / 废单 {n_dead}，成交额约 {total_traded:,.0f} 元")


if __name__ == "__main__":
    main()
