"""
知识库存储（知识板块）

职责：SQLite 存文章（原文 + 中文摘要），FTS5 全文检索。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd


class KnowledgeStorage:
    """知识库存储。默认相对 quant-system 目录。"""

    def __init__(self, db_path: str = "knowledge/knowledge.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _conn(self):
        return sqlite3.connect(str(self.db_path))

    def _init_db(self):
        conn = self._conn()
        cur = conn.cursor()
        # 文章表（原文 + 中文摘要分列）
        cur.execute("""
            CREATE TABLE IF NOT EXISTS articles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                link TEXT UNIQUE,
                title TEXT,
                title_zh TEXT,
                summary TEXT,
                summary_zh TEXT,
                source TEXT,
                category TEXT,
                published TEXT
            )
        """)
        # FTS5 全文检索（对中英文标题/摘要建索引）
        cur.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS articles_fts USING fts5(
                title, title_zh, summary, summary_zh, source, category,
                content='articles', content_rowid='id'
            )
        """)
        # 触发器：文章插入/删除时同步 FTS 索引
        cur.execute("""
            CREATE TRIGGER IF NOT EXISTS articles_ai AFTER INSERT ON articles BEGIN
                INSERT INTO articles_fts(rowid, title, title_zh, summary, summary_zh, source, category)
                VALUES (new.id, new.title, new.title_zh, new.summary, new.summary_zh, new.source, new.category);
            END
        """)
        cur.execute("""
            CREATE TRIGGER IF NOT EXISTS articles_ad AFTER DELETE ON articles BEGIN
                INSERT INTO articles_fts(articles_fts, rowid, title, title_zh, summary, summary_zh, source, category)
                VALUES ('delete', old.id, old.title, old.title_zh, old.summary, old.summary_zh, old.source, old.category);
            END
        """)
        conn.commit()
        conn.close()

    def upsert_articles(self, df: pd.DataFrame):
        """按 link 去重写入。"""
        if df.empty:
            return
        conn = self._conn()
        cur = conn.cursor()
        for _, row in df.iterrows():
            cur.execute("""
                INSERT INTO articles (link, title, title_zh, summary, summary_zh, source, category, published)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(link) DO UPDATE SET
                    title=excluded.title, summary=excluded.summary, published=excluded.published
            """, (
                row.get("link"), row.get("title"), row.get("title_zh"),
                row.get("summary"), row.get("summary_zh"),
                row.get("source"), row.get("category"), row.get("published"),
            ))
        conn.commit()
        conn.close()

    def search(self, keyword: str, limit: int = 20) -> pd.DataFrame:
        """全文检索（FTS5）。"""
        conn = self._conn()
        df = pd.read_sql("""
            SELECT a.id, a.title, a.title_zh, a.link, a.source, a.category, a.published,
                   bm25(articles_fts) AS score
            FROM articles_fts
            JOIN articles a ON a.id = articles_fts.rowid
            WHERE articles_fts MATCH ?
            ORDER BY score
            LIMIT ?
        """, conn, params=(keyword, limit))
        conn.close()
        return df

    def recent(self, limit: int = 50, category: str | None = None) -> pd.DataFrame:
        """最近文章，可按分类过滤。"""
        conn = self._conn()
        if category:
            df = pd.read_sql("""
                SELECT * FROM articles WHERE category = ? ORDER BY published DESC LIMIT ?
            """, conn, params=(category, limit))
        else:
            df = pd.read_sql("""
                SELECT * FROM articles ORDER BY published DESC LIMIT ?
            """, conn, params=(limit,))
        conn.close()
        return df
