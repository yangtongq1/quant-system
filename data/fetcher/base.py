"""
数据采集器抽象接口（DataFetcher）

约定：
- 所有 fetch 方法返回 pandas.DataFrame，列名为英文标准列（date/open/high/low/close/volume/amount）。
- 股票池必须含退市股（消除幸存者偏差），由 fetch_stock_list 返回。
- 复权口径：行情统一采「不复权」+ 复权因子，或显式声明 adjust 参数。
"""

from __future__ import annotations

from abc import ABC, abstractmethod

import pandas as pd


class DataFetcher(ABC):
    """数据源抽象。智谱可新增 supermind_fetcher 等实现。"""

    @abstractmethod
    def fetch_daily_bars(self, code: str, start: str, end: str, adjust: str = "none") -> pd.DataFrame:
        """单只 A 股日线。adjust: none/qfq/hfq。"""

    @abstractmethod
    def fetch_stock_list(self) -> pd.DataFrame:
        """全市场股票列表（含退市股），列：code/name/exchange/status/list_date/delist_date。"""

    @abstractmethod
    def fetch_etf_bars(self, code: str, start: str, end: str) -> pd.DataFrame:
        """ETF 日线（黄金 ETF 518880 / 纳指 ETF 513100 等）。"""

    @abstractmethod
    def fetch_trade_calendar(self, start: str, end: str) -> pd.DataFrame:
        """交易日历，列：date/is_open。"""

    def fetch_fundamentals(self, code: str) -> pd.DataFrame:
        """基本面数据（可选，默认空实现，M3 前可返回空）。"""
        return pd.DataFrame()
