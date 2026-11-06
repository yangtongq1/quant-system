"""
财报批量入库（东财业绩报表，一次调用拿全市场单季度）

用法：
  python scripts/fetch_fundamentals.py --quarters 12        # 最近 12 个季度
  python scripts/fetch_fundamentals.py --all-history       # 2014 年至今全部季度

存储：SQLite fundamentals 表（长表）
  code / period / report_date(公告日) / roe / gross_margin /
  revenue_yoy / profit_yoy / eps / bvps / industry

红线：
- point-in-time：存「最新公告日期」，因子计算时按公告日对齐（防未来函数）。
- 数据不编造：空值存 NULL。
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
import time
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

DB = ROOT / "data" / "quant.db"

# 全部报告期（2014 至今，每年 4 个季度）
def all_quarters(start_year: int = 2014) -> list[str]:
    quarters = []
    now = pd.Timestamp.now()
    for y in range(start_year, now.year + 1):
        for md in ("0331", "0630", "0930", "1231"):
            q = f"{y}{md}"
            if pd.Timestamp(f"{y}-{md[:2]}-{md[2:]}") <= now:
                quarters.append(q)
    return quarters


def init_table(conn: sqlite3.Connection):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS fundamentals (
            code TEXT, period TEXT, report_date TEXT,
            roe REAL, gross_margin REAL, revenue_yoy REAL, profit_yoy REAL,
            eps REAL, bvps REAL, industry TEXT,
            PRIMARY KEY (code, period)
        )
    """)
    conn.commit()


def fetch_quarter(quarter: str) -> pd.DataFrame:
    """抓单个报告期全市场业绩报表。"""
    import akshare as ak
    df = ak.stock_yjbb_em(date=quarter)
    if df is None or df.empty:
        return pd.DataFrame()
    rename = {
        "股票代码": "code",
        "每股收益": "eps",
        "营业总收入-同比增长": "revenue_yoy",
        "净利润-同比增长": "profit_yoy",
        "每股净资产": "bvps",
        "净资产收益率": "roe",
        "销售毛利率": "gross_margin",
        "所处行业": "industry",
        "最新公告日期": "report_date",
    }
    df = df.rename(columns={k: v for k, v in rename.items() if k in df.columns})
    if "code" not in df.columns:
        return pd.DataFrame()
    df = df.copy()
    df["code"] = df["code"].astype(str).str.zfill(6)
    df["period"] = f"{quarter[:4]}-{quarter[4:6]}-{quarter[6:]}"
    # 数值列转数字（'-' 等脏值 → NaN）
    for c in ("roe", "gross_margin", "revenue_yoy", "profit_yoy", "eps", "bvps"):
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    cols = [c for c in ("code", "period", "report_date", "roe", "gross_margin",
                        "revenue_yoy", "profit_yoy", "eps", "bvps", "industry")
            if c in df.columns]
    return df[cols]


def upsert(conn: sqlite3.Connection, df: pd.DataFrame):
    if df.empty:
        return 0
    n = 0
    for _, r in df.iterrows():
        try:
            conn.execute("""
                INSERT INTO fundamentals (code, period, report_date, roe, gross_margin,
                                          revenue_yoy, profit_yoy, eps, bvps, industry)
                VALUES (?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(code, period) DO UPDATE SET
                    report_date=excluded.report_date, roe=excluded.roe,
                    gross_margin=excluded.gross_margin, revenue_yoy=excluded.revenue_yoy,
                    profit_yoy=excluded.profit_yoy, eps=excluded.eps, bvps=excluded.bvps,
                    industry=excluded.industry
            """, tuple(r.get(c) for c in ("code", "period", "report_date", "roe",
                                           "gross_margin", "revenue_yoy", "profit_yoy",
                                           "eps", "bvps", "industry")))
            n += 1
        except Exception:  # noqa: BLE001
            continue
    conn.commit()
    return n


def main():
    parser = argparse.ArgumentParser(description="财报批量入库")
    parser.add_argument("--quarters", type=int, default=0, help="最近 N 个季度")
    parser.add_argument("--all-history", action="store_true", help="2014 年至今全部")
    parser.add_argument("--from", dest="from_q", default="", help="指定报告期，如 20240331")
    args = parser.parse_args()

    if args.from_q:
        quarters = [args.from_q]
    elif args.all_history:
        quarters = all_quarters()
    elif args.quarters > 0:
        quarters = all_quarters()[-args.quarters:]
    else:
        quarters = all_quarters()[-8:]  # 默认最近 8 季

    conn = sqlite3.connect(str(DB))
    init_table(conn)

    ok, fail = 0, 0
    for i, q in enumerate(quarters):
        got = False
        for attempt in range(3):
            try:
                df = fetch_quarter(q)
                if df is not None and not df.empty:
                    n = upsert(conn, df)
                    print(f"[fund] {q}: {n} 条入库", flush=True)
                    ok += 1
                else:
                    print(f"[fund] {q}: 无数据（未披露？）", flush=True)
                got = True
                break
            except Exception as e:  # noqa: BLE001
                if attempt == 2:
                    print(f"[fund] {q} 失败: {type(e).__name__} {str(e)[:80]}", flush=True)
                else:
                    time.sleep(8 * (attempt + 1))
        if not got:
            fail += 1
        time.sleep(3)  # 限流间隔

    total = conn.execute("SELECT COUNT(*) FROM fundamentals").fetchone()[0]
    conn.close()
    print(f"[fund] 完成：{ok} 季成功 / {fail} 失败，库内共 {total} 条")


if __name__ == "__main__":
    main()
