"""ST/退市股日线清理（看板一键操作台复用）。

判定（与策略过滤同口径）：
  - stocks.is_st=1 或名称含 ST → ST 股
  - stocks.status=delisted 或名称含「退」→ 退市股
动作：删除对应 data/bars/*.parquet；stocks 表记录保留（含 delisted 标记），
策略池自动缩小（run_paper_signals 按 parquet 文件枚举池）。

用法：python scripts/clean_st_delist.py [--dry-run]
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def classify() -> tuple[list[str], list[str]]:
    """返回 (st_codes, delist_codes)。"""
    db = ROOT / "data" / "quant.db"
    if not db.exists():
        return [], []
    with sqlite3.connect(str(db)) as conn:
        rows = conn.execute("SELECT code, name, is_st, status FROM stocks").fetchall()
    st_codes, delist_codes = [], []
    for code, name, is_st, status in rows:
        name = name or ""
        status = (status or "").lower()
        if status == "delisted" or "退" in name:
            delist_codes.append(code)
        elif is_st == 1 or "ST" in name.upper():
            st_codes.append(code)
    return st_codes, delist_codes


def run(dry_run: bool = False) -> dict:
    """执行清理。返回 {removed_st, removed_delist, remaining, errors}。"""
    bars_dir = ROOT / "data" / "bars"
    st_codes, delist_codes = classify()
    existing = {p.stem for p in bars_dir.glob("*.parquet")}
    targets = [c for c in st_codes + delist_codes if c in existing]
    removed_st = removed_delist = 0
    errors: list[str] = []
    for c in targets:
        f = bars_dir / f"{c}.parquet"
        if dry_run:
            continue
        try:
            f.unlink()
            if c in st_codes:
                removed_st += 1
            else:
                removed_delist += 1
        except OSError as e:
            errors.append(f"{c}: {e}")
    remaining = len(list(bars_dir.glob("*.parquet")))
    return {"removed_st": removed_st, "removed_delist": removed_delist,
            "remaining": remaining, "errors": errors}


if __name__ == "__main__":
    dry = "--dry-run" in sys.argv
    st_c, dl_c = classify()
    bars = {p.stem for p in (ROOT / "data" / "bars").glob("*.parquet")}
    n_st = len([c for c in st_c if c in bars])
    n_dl = len([c for c in dl_c if c in bars])
    print(f"库内待清理：ST {n_st} 只 + 退市 {n_dl} 只")
    if dry:
        print("[dry-run] 未删除。去掉 --dry-run 执行。")
        sys.exit(0)
    r = run()
    print(f"已删除：ST {r['removed_st']} + 退市 {r['removed_delist']}，"
          f"库剩余 {r['remaining']} 只，错误 {len(r['errors'])}")
    for e in r["errors"][:10]:
        print(f"  {e}")
