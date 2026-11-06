"""
全市场日线批量入库（断点续传）

用法：
  python scripts/fetch_universe.py --start 20200101              # 全市场（含退市）
  python scripts/fetch_universe.py --start 20200101 --limit 100   # 限量测试
  python scripts/fetch_universe.py --start 20200101 --all        # 含退市股

特点：
- 断点续传：跳过已入库标的（data/bars/*.parquet 已存在即跳过，--force 重采）
- 限流友好：每只间隔 0.5s，失败重试 3 次，单只失败不中断
- 进度可见：每 10 只打印一次进度
- 优先指数成分股：先沪深300+中证500，再全市场
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from data.cleaner import clean_daily_bars          # noqa: E402
from data.fetcher.akshare_fetcher import AkshareFetcher  # noqa: E402
from data.storage import Storage                   # noqa: E402


def index_constituents() -> list[str]:
    """指数成分股优先（沪深300 + 中证500），失败返回空。"""
    import akshare as ak
    codes: list[str] = []
    for func, col in ((ak.index_stock_cons_csindex, "000300"),
                      (ak.index_stock_cons_csindex, "000905")):
        try:
            df = func(col)
            code_col = "成分券代码" if "成分券代码" in df.columns else "代码"
            codes.extend(df[code_col].astype(str).str.zfill(6).tolist())
            time.sleep(1)
        except Exception:  # noqa: BLE001
            continue
    return list(dict.fromkeys(codes))


def main():
    parser = argparse.ArgumentParser(description="全市场日线批量入库")
    parser.add_argument("--start", default="20200101")
    parser.add_argument("--end", default="20261231")
    parser.add_argument("--limit", type=int, default=0, help="限量（测试用），0=不限")
    parser.add_argument("--all", action="store_true", help="含退市股（默认仅存续）")
    parser.add_argument("--index-first", action="store_true", default=True,
                        help="指数成分股优先（默认开）")
    parser.add_argument("--force", action="store_true", help="重采已入库标的")
    parser.add_argument("--min-list-date", default="20190101",
                        help="仅采该日期前上市的（上市太晚的历史不足）")
    args = parser.parse_args()

    storage = Storage(str(ROOT / "data" / "quant.db"), str(ROOT / "data" / "bars"))
    bars_dir = ROOT / "data" / "bars"

    # 标的池：存续 + 可选退市
    conn = sqlite3.connect(str(ROOT / "data" / "quant.db"))
    if args.all:
        rows = conn.execute("SELECT code FROM stocks WHERE status IN ('listed','delisted')").fetchall()
    else:
        rows = conn.execute("SELECT code FROM stocks WHERE status = 'listed'").fetchall()
    conn.close()
    all_codes = [r[0] for r in rows]

    # 排除上市太晚的（因子需要 ≥120 日历史）
    conn = sqlite3.connect(str(ROOT / "data" / "quant.db"))
    listed_dates = dict(conn.execute("SELECT code, list_date FROM stocks").fetchall())
    conn.close()

    def eligible(code: str) -> bool:
        ld = listed_dates.get(code, "")
        if not ld:
            return True  # 无上市日期信息，保留（多数存续股）
        try:
            return ld.replace("-", "") <= args.min_list_date
        except Exception:  # noqa: BLE001
            return True

    pool = [c for c in all_codes if eligible(c)]

    # 排除北交所（流动性差、30% 涨跌停，选股池通常剔除）
    pool = [c for c in pool if not c.startswith(("8", "4", "92"))]

    # 指数成分股优先
    if args.index_first:
        try:
            idx = index_constituents()
            idx_set = set(idx)
            pool = idx + [c for c in pool if c not in idx_set]
            print(f"[universe] 指数成分股优先: {len(idx)} 只")
        except Exception as e:  # noqa: BLE001
            print(f"[universe] 指数成分股获取失败（按默认顺序）: {e}")

    # 断点续传：跳过已入库
    if not args.force:
        done = {p.stem for p in bars_dir.glob("*.parquet")}
        todo = [c for c in pool if c not in done]
        skipped = len(pool) - len(todo)
    else:
        todo = pool
        skipped = 0
    if args.limit > 0:
        todo = todo[: args.limit]

    print(f"[universe] 计划采集 {len(todo)} 只（已跳过 {skipped}），区间 {args.start}~{args.end}")

    fetcher = AkshareFetcher()
    ok, fail = 0, 0
    t0 = time.time()
    for i, code in enumerate(todo):
        # 单只三次重试
        got = False
        for attempt in range(3):
            try:
                raw = fetcher.fetch_daily_bars(code, args.start, args.end,
                                                with_adj_factor=(attempt == 0))
                if raw is not None and not raw.empty:
                    cleaned = clean_daily_bars(raw, strict=False)
                    storage.save_bars(code, cleaned)
                    ok += 1
                    got = True
                break
            except Exception:  # noqa: BLE001
                time.sleep(3 * (attempt + 1))
        if not got and raw is not None and not isinstance(raw, Exception):
            # 接口返回空 = 正常（新股/停牌），不算失败
            pass
        if not got:
            fail += 1
        if (i + 1) % 10 == 0:
            rate = (i + 1) / (time.time() - t0)
            eta_min = (len(todo) - i - 1) / max(rate, 0.01) / 60
            print(f"[universe] 进度 {i + 1}/{len(todo)}（ok={ok} fail={fail}），"
                  f"速率 {rate:.1f} 只/秒，预计剩余 {eta_min:.0f} 分钟", flush=True)
        time.sleep(0.5)

    print(f"[universe] 完成：成功 {ok} / 失败 {fail} / 跳过 {skipped}")


if __name__ == "__main__":
    main()
