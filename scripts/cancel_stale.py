"""撤旧单（cancel_stale）：run-paper 前置撤掉我们的在挂柜台委托。

背景（2026-11-13 红线）：东莞模拟柜台批次撮合延迟 30-50 分钟——
昨日 run 的委托可能仍在挂（stat=50/53/55/57），今日 run 直接下新单会重复委托
（差额基准只含柜台已成交量，不含在挂量）。

识别口径（三层，防误伤用户自有委托）：
  1. remark == "quant-system"（当日单柜台回显 remark）
  2. DB orders (code, side, volume) 精确匹配（隔日单柜台不回显 remark，用我们下过的单匹配）
  3. 兜底：主板 code + 管理范围内 + PAPER_START(2026-11-12) 之后下的单
     （创业板/科创板 300/301/688 永不触碰——策略 main_board_only，用户自有单多在此）

用法：
  python scripts/cancel_stale.py            # 执行撤旧单（幂等，撤完即空）
  python main.py cancel-stale               # CLI 入口
  run-paper --qmt 前置自动执行（main.py 调用）
"""
from __future__ import annotations

import sqlite3
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# 未终结柜台状态（50 已报 / 53 撤单中 / 55 部成 / 57 部成待撤；54/56/58 终态）
_ACTIVE_STAT = {50, 53, 55, 57}
# 创业板/科创板前缀（策略 main_board_only=true 永不触碰，用户自有单多在此）
_GEM_STAR_PREFIX = ("300", "301", "688")
# 100 万仓位重建日（此前的挂单属旧调试仓，一并清理）
_PAPER_START_TS = None


def _paper_start_ts() -> float:
    global _PAPER_START_TS
    if _PAPER_START_TS is None:
        try:
            from scripts.paper_equity import PAPER_START
            dt = datetime.strptime(PAPER_START, "%Y-%m-%d")
        except Exception:  # noqa: BLE001
            dt = datetime(2026, 11, 12)
        _PAPER_START_TS = dt.timestamp()
    return _PAPER_START_TS


def _db_order_keys() -> set[tuple[str, str, int]]:
    """DB orders 全量 (code, side, volume) 键（我们下过的所有单）。"""
    db = ROOT / "data" / "quant.db"
    keys: set[tuple[str, str, int]] = set()
    if not db.exists():
        return keys
    try:
        with sqlite3.connect(str(db)) as conn:
            for code, side, vol in conn.execute(
                    "SELECT code, side, volume FROM orders"):
                if code and side and vol:
                    keys.add((str(code), str(side), int(vol)))
    except Exception:  # noqa: BLE001
        pass
    return keys


def _is_ours(o) -> bool:
    """判断柜台委托是否我们的（三层口径，防误伤用户自有单）。"""
    remark = getattr(o, "order_remark", "") or ""
    if remark == "quant-system":
        return True  # ① 当日单：柜台回显我们的 remark
    code = str(o.stock_code).split(".")[0]
    if code.startswith(_GEM_STAR_PREFIX):
        return False  # 创业板/科创板：策略永不碰（用户自有单），直接排除
    # ② DB 精确匹配（隔日单 remark 不回显，用我们下过的 (code,side,vol) 匹配）
    if (code, "buy" if o.order_type == 23 else "sell",
            int(getattr(o, "order_volume", 0) or 0)) in _DB_KEYS:
        return True
    # ③ 兜底：主板 + 管理范围内 + 正式运行期间（PAPER_START 后）
    if code in _MANAGED and float(getattr(o, "order_time", 0) or 0) >= _paper_start_ts():
        return True
    return False


# 模块级缓存（一次运行内复用）
_DB_KEYS: set = set()
_MANAGED: set = set()
_LOADED = False


def _load_context() -> None:
    global _LOADED, _DB_KEYS, _MANAGED
    if _LOADED:
        return
    _DB_KEYS = _db_order_keys()
    db = ROOT / "data" / "quant.db"
    if db.exists():
        try:
            with sqlite3.connect(str(db)) as conn:
                _MANAGED = {str(r[0]) for r in conn.execute(
                    "SELECT DISTINCT code FROM orders") if r[0]}
                _MANAGED |= {str(r[0]) for r in conn.execute(
                    "SELECT code FROM positions WHERE volume > 0") if r[0]}
        except Exception:  # noqa: BLE001
            pass
    _LOADED = True


def cancel_stale(verbose: bool = True) -> dict:
    """撤掉我们的在挂柜台委托（未终结状态）。返回摘要 dict。"""
    from execution.qmt_broker import QmtBroker

    _load_context()
    broker = QmtBroker(mode="paper")
    if broker.dry_run:
        if verbose:
            print("[cancel-stale] QMT 未连接，跳过（无委托可撤）")
        return {"cancelled": [], "skipped": [], "error": broker.last_error}

    cancelled: list[dict] = []
    skipped: list[dict] = []
    for o in broker.get_orders():
        st = int(getattr(o, "order_status", -1) or -1)
        if st not in _ACTIVE_STAT:
            continue  # 已终态（已成/已撤）
        if not _is_ours(o):
            continue  # 非我们的单（用户自有），绝不触碰
        code_full = str(o.stock_code)
        code = code_full.split(".")[0]
        market = 0 if code_full.endswith(".SH") else 1  # 0=上海 1=深圳
        oid = int(getattr(o, "order_id", 0) or 0)
        sysid = str(getattr(o, "order_sysid", "") or "")
        # 当日单：柜台委托号 order_id（1209008xxx）；隔日单：order_id=0 只能用 sysid
        if oid:
            ok = broker.cancel(str(oid))  # QmtBroker.cancel → cancel_order_stock
        elif sysid:
            try:
                ok = bool(broker.trader.cancel_order_stock_sysid(
                    broker._account_obj, market, sysid) == 0)
            except Exception:  # noqa: BLE001
                ok = False
        else:
            continue
        rec = {"code": code, "order_id": oid, "sysid": sysid, "stat": st,
               "vol": int(getattr(o, "order_volume", 0) or 0),
               "traded": int(getattr(o, "traded_volume", 0) or 0)}
        (cancelled if ok else skipped).append(rec)
        if verbose:
            mark = "已撤" if ok else "撤单失败"
            via = f"order_id={oid}" if oid else f"sysid={sysid}"
            print(f"[cancel-stale] {mark} {code}（{via}，vol={rec['vol']} "
                  f"traded={rec['traded']} stat={st}）")

    if verbose:
        n = len(cancelled) + len(skipped)
        print(f"[cancel-stale] 完成：撤 {len(cancelled)} 笔"
              f"（失败 {len(skipped)} 笔）"
              + ("" if n else "，无在挂委托"))
    return {"cancelled": cancelled, "skipped": skipped, "error": ""}


if __name__ == "__main__":
    cancel_stale()
