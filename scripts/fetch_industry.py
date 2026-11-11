"""行业数据采集（东财行业板块成分 → stocks.industry 列）。

用法：python scripts/fetch_industry.py
限流恢复后运行（东财 push2 限流时约 5-40 分钟）。
幂等：重复运行覆盖更新（板块成分变动自动跟随）。
"""
from __future__ import annotations

import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "quant.db"


def run() -> dict:
    import akshare as ak

    # 1. 行业板块列表（板块名 → 东财代码）
    boards = ak.stock_board_industry_name_em()
    board_list = boards["板块名称"].tolist()
    print(f"行业板块 {len(board_list)} 个")

    # 2. 逐板块拉成分股 → code → industry
    code_industry: dict[str, str] = {}
    for i, board in enumerate(board_list):
        try:
            cons = ak.stock_board_industry_cons_em(symbol=board)
            for c in cons["代码"].astype(str):
                code_industry[c] = board
        except Exception as e:  # noqa: BLE001
            print(f"  [{i+1}/{len(board_list)}] {board} 失败: {type(e).__name__}")
            time.sleep(2)
            continue
        if (i + 1) % 10 == 0:
            print(f"  [{i+1}/{len(board_list)}] 累计 {len(code_industry)} 只")
        time.sleep(1)  # 限流保护

    # 3. 写 stocks.industry
    with sqlite3.connect(str(DB)) as conn:
        cur = conn.cursor()
        # 加列（幂等）
        cols = [r[1] for r in cur.execute("PRAGMA table_info(stocks)").fetchall()]
        if "industry" not in cols:
            cur.execute("ALTER TABLE stocks ADD COLUMN industry TEXT")
        n = 0
        for code, ind in code_industry.items():
            cur.execute("UPDATE stocks SET industry=? WHERE code=?", (ind, code))
            n += cur.rowcount
        conn.commit()
    return {"boards": len(board_list), "mapped": len(code_industry), "updated": n}


if __name__ == "__main__":
    r = run()
    print(f"行业采集完成：板块 {r['boards']}，映射 {r['mapped']} 只，"
          f"stocks 表更新 {r['updated']} 条")
