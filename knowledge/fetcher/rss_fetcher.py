"""
RSS 采集器（知识板块）

职责：从 sources.yaml 配置的免费 RSS 源抓取文章，输出标准化的文章列表。
"""

from __future__ import annotations

from pathlib import Path

import feedparser
import pandas as pd
import yaml


class RssFetcher:
    """抓取多个 RSS 源，合并为统一 DataFrame。"""

    def __init__(self, sources_path: str | Path):
        self.sources = self._load_sources(Path(sources_path))

    @staticmethod
    def _load_sources(path: Path):
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return data.get("sources", [])

    def fetch_source(self, source: dict) -> list[dict]:
        """抓取单个源，返回文章 dict 列表。"""
        feed = feedparser.parse(source["url"])
        items = []
        for entry in feed.entries:
            items.append({
                "title": entry.get("title", "").strip(),
                "link": entry.get("link", "").strip(),
                "summary": _strip_html(entry.get("summary", "")),
                "published": entry.get("published", ""),
                "source": source["name"],
                "category": source.get("category", ""),
                "lang": source.get("lang", "en"),
            })
        return items

    def fetch_all(self) -> pd.DataFrame:
        """抓取所有源，返回合并 DataFrame（单个源失败不中断）。"""
        all_items: list[dict] = []
        for src in self.sources:
            try:
                items = self.fetch_source(src)
                all_items.extend(items)
                print(f"[rss] {src['name']}: {len(items)} 条")
            except Exception as e:  # noqa: BLE001
                print(f"[rss] 抓取 {src['name']} 失败: {e}")
        if not all_items:
            return pd.DataFrame(columns=[
                "title", "link", "summary", "published", "source", "category", "lang",
            ])
        return pd.DataFrame(all_items)


def _strip_html(text: str) -> str:
    """去掉摘要里的 HTML 标签。"""
    import re
    return re.sub(r"<[^>]+>", "", text or "").strip()
