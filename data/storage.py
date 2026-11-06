"""
数据存储模块（M1）

设计：元数据（股票列表/交易日历/订单等）存 SQLite；日线 K 线存 Parquet（列式，便于因子批量计算）。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd


class Storage:
    """本地存储。默认相对 quant-system 目录。"""

    def __init__(self, db_path: str = "data/quant.db", bars_dir: str = "data/bars"):
        self.db_path = Path(db_path)
        self.bars_dir = Path(bars_dir)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.bars_dir.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _conn(self):
        return sqlite3.connect(str(self.db_path))

    def _init_db(self):
        conn = self._conn()
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS stocks (
                code TEXT PRIMARY KEY, name TEXT, exchange TEXT,
                status TEXT, list_date TEXT, delist_date TEXT,
                board TEXT, is_st INTEGER
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS trade_calendar (
                date TEXT PRIMARY KEY, is_open INTEGER
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS orders (
                order_id TEXT PRIMARY KEY, code TEXT, side TEXT,
                price REAL, volume INTEGER, status TEXT,
                create_time TEXT, update_time TEXT, strategy TEXT
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS trades (
                trade_id TEXT PRIMARY KEY, order_id TEXT, code TEXT,
                side TEXT, price REAL, volume INTEGER, fee REAL, time TEXT
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS positions (
                code TEXT PRIMARY KEY, volume INTEGER, avg_cost REAL, market_value REAL
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS accounts (
                account_id TEXT PRIMARY KEY, cash REAL, total_asset REAL, update_time TEXT
            )
        """)
        conn.commit()
        conn.close()

    # ---- 股票列表 ----
    def save_stocks(self, df: pd.DataFrame):
        conn = self._conn()
        df.to_sql("stocks", conn, if_exists="replace", index=False)
        conn.commit()
        conn.close()

    def load_stocks(self) -> pd.DataFrame:
        conn = self._conn()
        df = pd.read_sql("SELECT * FROM stocks", conn)
        conn.close()
        return df

    # ---- 交易日历 ----
    def save_calendar(self, df: pd.DataFrame):
        conn = self._conn()
        df.to_sql("trade_calendar", conn, if_exists="replace", index=False)
        conn.commit()
        conn.close()

    def load_calendar(self) -> pd.DataFrame:
        conn = self._conn()
        df = pd.read_sql("SELECT * FROM trade_calendar", conn)
        conn.close()
        df["date"] = pd.to_datetime(df["date"])
        return df

    # ---- 日线 K 线（Parquet） ----
    def _bars_path(self, code: str) -> Path:
        return self.bars_dir / f"{code}.parquet"

    def save_bars(self, code: str, df: pd.DataFrame):
        df.to_parquet(self._bars_path(code), index=False)

    def load_bars(self, code: str) -> pd.DataFrame:
        return pd.read_parquet(self._bars_path(code))
