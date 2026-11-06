"""
基本面数据 point-in-time 测试（红线：财报公告日前不可见）
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from data.fundamentals import industry_map, point_in_time_panel


def _fund():
    """构造两期财报：
    - 2024Q1（公告 2024-04-28，ROE=10）
    - 2024Q2（公告 2024-08-20，ROE=22）
    """
    return pd.DataFrame({
        "code": ["600519", "600519", "000001", "000001"],
        "period": ["2024-03-31", "2024-06-30", "2024-03-31", "2024-06-30"],
        "report_date": ["2024-04-28", "2024-08-20", "2024-04-25", "2024-08-22"],
        "roe": [10.0, 22.0, 5.0, 8.0],
        "gross_margin": [91.0, 92.0, 40.0, 41.0],
        "revenue_yoy": [15.0, 18.0, 3.0, 2.0],
        "profit_yoy": [20.0, 25.0, 1.0, -2.0],
        "eps": [10.0, 12.0, 1.5, 1.6],
        "bvps": [120.0, 130.0, 20.0, 21.0],
        "industry": ["白酒", "白酒", "银行", "银行"],
    })


def test_point_in_time_no_lookahead():
    """公告日前不可见：Q2 公告(8/20)前只能看到 Q1 的 ROE。"""
    fund = _fund()
    fund["report_date"] = pd.to_datetime(fund["report_date"])
    fund["period"] = pd.to_datetime(fund["period"])
    dates = pd.DatetimeIndex([
        "2024-04-01",  # Q1 公告(4/28)前：应全 NaN
        "2024-05-06",  # Q1 公告后：ROE=10
        "2024-08-19",  # Q2 公告(8/20)前：仍应是 Q1 的 10
        "2024-08-21",  # Q2 公告后：ROE=22
    ])
    panel = point_in_time_panel(fund, "roe", dates)
    assert panel.loc["2024-04-01", "600519"] is None or pd.isna(panel.loc["2024-04-01", "600519"]), \
        "Q1 公告前不应看到任何数据"
    assert panel.loc["2024-05-06", "600519"] == 10.0, "Q1 公告后应见 Q1 ROE"
    assert panel.loc["2024-08-19", "600519"] == 10.0, "Q2 公告前仍应只见 Q1 ROE（防未来函数）"
    assert panel.loc["2024-08-21", "600519"] == 22.0, "Q2 公告后应见 Q2 ROE"


def test_panel_multi_codes():
    """多标的面板 + 公告日差异正确。"""
    fund = _fund()
    fund["report_date"] = pd.to_datetime(fund["report_date"])
    fund["period"] = pd.to_datetime(fund["period"])
    dates = pd.DatetimeIndex(["2024-04-26", "2024-04-29"])
    panel = point_in_time_panel(fund, "roe", dates)
    # 000001 公告 4/25，4/26 可见；600519 公告 4/28，4/26 不可见、4/29 可见
    assert panel.loc["2024-04-26", "000001"] == 5.0
    assert pd.isna(panel.loc["2024-04-26", "600519"])
    assert panel.loc["2024-04-29", "600519"] == 10.0


def test_industry_map():
    fund = _fund()
    ind = industry_map(fund)
    assert ind["600519"] == "白酒"
    assert ind["000001"] == "银行"
