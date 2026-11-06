"""
重建 fundamentals.period 列。

策略：period 反推有歧义（4 月底既有一季报也有延迟年报），无法逐行 UPDATE（撞唯一约束）。
正确做法：把整表读出，按 (code, report_date) 排序后，用「公告日 → 报告期」反推 +
冲突合并（ON CONFLICT 择 report_date 更近者），重建临时表后整体替换。

幂等：可重复执行。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "quant.db"

COLS = ("code", "period", "report_date", "roe", "gross_margin", "revenue_yoy",
        "profit_yoy", "eps", "bvps", "industry")


def infer_period(report_date: str) -> str:
    """由公告日反推报告期（尽力而为，冲突由合并逻辑兜底）。"""
    y, m = int(report_date[:4]), int(report_date[5:7])
    if 1 <= m <= 3:
        return f"{y - 1}-12-31"
    if 4 <= m <= 7:
        return f"{y}-03-31"
    if 8 <= m <= 9:
        return f"{y}-06-30"
    return f"{y}-09-30"


def main():
    import pandas as pd

    conn = sqlite3.connect(str(DB))
    df = pd.read_sql("SELECT * FROM fundamentals", conn)
    print(f"[rebuild] 读出 {len(df)} 条")

    # 反推 period
    mask = df["period"].isna() | (df["period"].astype(str) == "")
    n_fix = int(mask.sum())
    df.loc[mask, "period"] = df.loc[mask, "report_date"].astype(str).map(infer_period)
    print(f"[rebuild] 反推 period: {n_fix} 条")

    # 冲突合并：同 (code, period) 多行时取 report_date 最新的一条
    df["_rd"] = pd.to_datetime(df["report_date"], errors="coerce")
    df = df.sort_values("_rd").drop_duplicates(subset=["code", "period"], keep="last")
    df = df.drop(columns=["_rd"])

    # 重建表
    df[["roe", "gross_margin", "revenue_yoy", "profit_yoy",
        "eps", "bvps"]] = df[["roe", "gross_margin", "revenue_yoy",
                              "profit_yoy", "eps", "bvps"]].apply(pd.to_numeric, errors="coerce")
    conn.execute("DROP TABLE IF EXISTS fundamentals")
    conn.execute("""
        CREATE TABLE fundamentals (
            code TEXT, period TEXT, report_date TEXT,
            roe REAL, gross_margin REAL, revenue_yoy REAL, profit_yoy REAL,
            eps REAL, bvps REAL, industry TEXT,
            PRIMARY KEY (code, period)
        )
    """)
    df[list(COLS)].to_sql("fundamentals", conn, if_exists="append", index=False)
    conn.commit()

    n = conn.execute("SELECT COUNT(*) FROM fundamentals").fetchone()[0]
    n_periods = conn.execute(
        "SELECT COUNT(DISTINCT period) FROM fundamentals").fetchone()[0]
    n_null = conn.execute(
        "SELECT COUNT(*) FROM fundamentals WHERE period IS NULL").fetchone()[0]
    conn.close()
    print(f"[rebuild] 完成：{n} 条 / {n_periods} 个报告期 / NULL {n_null}")


if __name__ == "__main__":
    main()
