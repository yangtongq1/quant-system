# -*- coding: utf-8 -*-
"""quant-system → Tick Stock Panel 推送桥。

把每日交易计划（orders）推送到局域网 Tick Stock Panel（TSP）的模拟盘账户，
用户可在 TSP 前端（http://192.168.18.249:3011 模拟盘页）看到当日买卖计划。

数据流：
  quant.db orders（当日 SUBMITTED/部分成交） → TSP /api/paper/orders（next_open 单）

幂等：tsp_push_state 表记录 (date, order_id)，已推送的单不再重复推。
用法：
  python scripts/push_to_tsp.py            # 推送当日订单
  python scripts/push_to_tsp.py --dry-run  # 只打印不提交
  python scripts/push_to_tsp.py --status    # 查看当日推送状态
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import urllib.error
import urllib.request
from datetime import datetime

ROOT = __file__.split("scripts")[0]
sys.path.insert(0, ROOT)

from core.logger import get_logger  # noqa: E402

log = get_logger("push_tsp", log_dir=f"{ROOT}logs")

# ---------------------------------------------------------------------------
# 配置（TSP 部署信息；改地址改这里或 config.yaml tsp 段）
# ---------------------------------------------------------------------------
TSP_BASE = "http://192.168.18.249:3011"   # TSP 前端（/api 代理到后端 3018）
TSP_ACCOUNT = "quant_system"              # 专用账户（首次推送自动创建）
DB_PATH = f"{ROOT}data/quant.db"


def _load_cfg() -> dict:
    """从 config.yaml 读 tsp 段（可覆盖上面的默认值）。"""
    try:
        import yaml
        with open(f"{ROOT}config/config.yaml", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
        return cfg.get("tsp") or {}
    except Exception:  # noqa: BLE001
        return {}


def _api(path: str, method: str = "GET", body: dict | None = None,
         timeout: int = 15, retries: int = 2) -> dict:
    """调 TSP API（经 vite 代理）；网络抖动自动重试（dev server 间歇不稳）。"""
    url = f"{TSP_BASE}{path}"
    data = json.dumps(body).encode() if body is not None else None
    last_err: Exception | None = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, data=data, method=method)
            if data is not None:
                req.add_header("Content-Type", "application/json")
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError:
            raise  # 4xx/5xx 业务错误不重试，直接抛
        except (urllib.error.URLError, OSError) as e:
            last_err = e
            if attempt < retries:
                import time
                time.sleep(3 * (attempt + 1))
    raise last_err  # type: ignore[misc]


def to_tsp_symbol(code: str) -> str:
    """000042 → 000042.SZ；600076 → 600076.SH；518880 → 518880.SH。"""
    code = code.strip()
    if "." in code:
        return code.upper()
    if code.startswith(("6", "5")):      # 沪市：60x 股票 / 51x,56x,58x ETF
        return f"{code}.SH"
    return f"{code}.SZ"                    # 深市：00x 股票 / 15x,16x ETF


def _ensure_state_table(con: sqlite3.Connection) -> None:
    con.execute(
        "CREATE TABLE IF NOT EXISTS tsp_push_state ("
        " date TEXT NOT NULL, order_id TEXT NOT NULL,"
        " tsp_order_id TEXT, status TEXT, pushed_at TEXT,"
        " PRIMARY KEY (date, order_id))"
    )
    con.commit()


def _ensure_account() -> str:
    """确保 TSP 侧账户存在（不存在则创建 100 万初始资金）。"""
    accounts = _api("/api/paper/accounts")
    for acc in accounts.get("accounts", []):
        if acc["id"] == TSP_ACCOUNT:
            return acc["id"]
    r = _api("/api/paper/account", "POST", {
        "initial_cash": 1_000_000.0,
        "account_id": TSP_ACCOUNT,
        "name": "quant-system策略仓",
    })
    log.info("[tsp] 账户已创建: %s", r["account"]["id"])
    return r["account"]["id"]


def _today_orders(con: sqlite3.Connection, today: str) -> list[dict]:
    """当日未成交订单（成交单已体现在持仓快照里，推了会双买/双卖）。

    只推 SUBMITTED（QMT 待成交）——它们是「尚未落地的意图」；
    FILLED 已结算进 positions；SKIPPED/废单无意义。
    """
    con.row_factory = sqlite3.Row
    cur = con.execute(
        "SELECT order_id, code, side, price, volume, status, create_time"
        " FROM orders WHERE create_time LIKE ? AND status = 'SUBMITTED'"
        " ORDER BY create_time",
        (f"{today}%",),
    )
    return [dict(r) for r in cur.fetchall()]


def _latest_prices(con: sqlite3.Connection, codes: list[str]) -> dict[str, float]:
    """保留接口：价格来源改用订单自身委托价（orders.price 即 QMT 限价）。"""
    return {}


def push_today(dry_run: bool = False) -> int:
    today = datetime.now().strftime("%Y-%m-%d")
    con = sqlite3.connect(DB_PATH)
    _ensure_state_table(con)
    orders = _today_orders(con, today)
    if not orders:
        log.info("[tsp] 当日无订单，跳过")
        return 0

    # 已推送集合
    pushed = set()
    con.row_factory = sqlite3.Row
    for r in con.execute(
        "SELECT order_id FROM tsp_push_state WHERE date = ?", (today,)
    ):
        pushed.add(r["order_id"])

    todo = [o for o in orders if o["order_id"] not in pushed]
    if not todo:
        log.info("[tsp] 当日 %d 笔订单已全部推送过，幂等跳过", len(orders))
        return 0

    prices = _latest_prices(con, sorted({o["code"] for o in todo}))

    if dry_run:
        for o in todo:
            sym = to_tsp_symbol(o["code"])
            px = prices.get(o["code"]) or o["price"]
            print(f"[dry] {o['side']:4s} {sym:12s} {o['volume']:6d}股 "
                  f"@{px} ref_price={px:.2f} ({o['status']})")
        print(f"[dry] 共 {len(todo)} 笔待推送（TSP 账户 {TSP_ACCOUNT}）")
        return len(todo)

    _ensure_account()
    ok = fail = 0
    now = datetime.now().isoformat(timespec="seconds")
    for o in todo:
        sym = to_tsp_symbol(o["code"])
        ref = prices.get(o["code"]) or float(o["price"] or 0)
        if ref <= 0:
            log.warning("[tsp] %s 无参考价，跳过（本地价 %s）", sym, o["price"])
            continue
        body = {
            "symbol": sym,
            "side": "buy" if o["side"] == "buy" else "sell",
            "qty": int(o["volume"]),
            "order_type": "next_open",
            "ref_price": round(ref, 2),
        }
        try:
            r = _api(f"/api/paper/orders?account={TSP_ACCOUNT}", "POST", body)
            tsp_id = r["order"]["id"]
            con.execute(
                "INSERT OR REPLACE INTO tsp_push_state VALUES (?,?,?,?,?)",
                (today, o["order_id"], tsp_id, r["order"]["status"], now),
            )
            con.commit()
            ok += 1
            log.info("[tsp] %s %s %d股 → %s", o["side"], sym, o["volume"], tsp_id)
        except (urllib.error.URLError, KeyError, OSError) as e:
            fail += 1
            log.error("[tsp] %s %s 推送失败: %s", o["side"], sym, e)
    log.info("[tsp] 推送完成：成功 %d / 失败 %d / 跳过 %d", ok, fail,
             len(todo) - ok - fail)
    return fail


def bootstrap_positions(dry_run: bool = False) -> int:
    """把 quant-system 当前持仓一次性推 TSP 建仓（amount 模式市价单）。

    用于打通初始化：TSP 账户是独立账本（100 万现金起步），直接推卖单会被拒
    （无持仓）。先用此命令把 54 只持仓镜像过去，之后每日订单差额才能对上。
    TSP 会按行情价成交（amount 模式按金额折算股数，向下取整百股）。
    """
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        "SELECT code, volume, avg_cost, market_value FROM positions ORDER BY code"
    ).fetchall()
    if not rows:
        log.info("[tsp] 本地无持仓，跳过建仓")
        return 0
    # 净值留痕里的策略市值作资金基准（最新一日）
    import csv
    strategy_mv = None
    try:
        with open(f"{ROOT}data/paper_equity.csv", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                strategy_mv = float(r["strategy_mv"])
    except Exception:  # noqa: BLE001
        pass
    total_cost = sum(r["avg_cost"] * r["volume"] for r in rows)
    log.info("[tsp] 建仓 %d 只，本地成本合计 %.0f（策略市值口径 %.0f）",
             len(rows), total_cost, strategy_mv or -1)
    if dry_run:
        for r in rows:
            print(f"[dry] buy {to_tsp_symbol(r['code']):12s} {r['volume']:7d}股 "
                  f"成本{r['avg_cost']:.3f}")
        return len(rows)

    _ensure_account()
    ok = fail = 0
    for r in rows:
        sym = to_tsp_symbol(r["code"])
        body = {
            "symbol": sym,
            "side": "buy",
            "qty": int(r["volume"]),
            "order_type": "market",
            "ref_price": round(r["avg_cost"], 2),
        }
        try:
            resp = _api(f"/api/paper/orders?account={TSP_ACCOUNT}", "POST", body)
            ok += 1
            log.info("[tsp] 建仓 %s %d股 → %s", sym, r["volume"], resp["order"]["id"])
        except (urllib.error.HTTPError, urllib.error.URLError, OSError, KeyError) as e:
            fail += 1
            log.error("[tsp] 建仓 %s 失败: %s", sym, e)
    log.info("[tsp] 建仓完成：成功 %d / 失败 %d", ok, fail)
    return fail


def show_status() -> None:
    today = datetime.now().strftime("%Y-%m-%d")
    con = sqlite3.connect(DB_PATH)
    _ensure_state_table(con)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        "SELECT * FROM tsp_push_state WHERE date = ? ORDER BY pushed_at", (today,)
    ).fetchall()
    if not rows:
        print(f"今日（{today}）无推送记录")
        return
    print(f"今日推送 {len(rows)} 笔：")
    for r in rows:
        print(f"  {r['order_id']} → {r['tsp_order_id']} [{r['status']}] @{r['pushed_at']}")


def main() -> None:
    ap = argparse.ArgumentParser(description="推送当日计划到 Tick Stock Panel")
    ap.add_argument("--dry-run", action="store_true", help="只打印不提交")
    ap.add_argument("--status", action="store_true", help="查看当日推送状态")
    ap.add_argument("--bootstrap", action="store_true",
                    help="把当前持仓一次性推 TSP 建仓（打通初始化用）")
    args = ap.parse_args()
    if args.status:
        show_status()
        return
    if args.bootstrap:
        sys.exit(1 if bootstrap_positions(dry_run=args.dry_run) else 0)
        return
    sys.exit(1 if push_today(dry_run=args.dry_run) else 0)


if __name__ == "__main__":
    main()
