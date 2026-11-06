"""数据采集器纯逻辑测试：板块判断 + 涨跌停幅度。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from data.fetcher.akshare_fetcher import (
    _board_of,
    _is_st,
    get_limit_rate,
    to_sina_symbol,
)


def test_board_of():
    assert _board_of("300750") == "gem"     # 创业板
    assert _board_of("688981") == "star"    # 科创板
    assert _board_of("600519") == "main"    # 主板
    assert _board_of("000001") == "main"    # 深主板
    assert _board_of("830799") == "bj"      # 北交所


def test_is_st():
    assert _is_st("*ST富润") is True
    assert _is_st("ST东北高") is True
    assert _is_st("平安银行") is False


def test_limit_rate():
    assert get_limit_rate("main", False) == 0.10   # 主板 10%
    assert get_limit_rate("gem", False) == 0.20    # 创业板 20%
    assert get_limit_rate("star", False) == 0.20   # 科创板 20%
    assert get_limit_rate("bj", False) == 0.30     # 北交所 30%
    assert get_limit_rate("main", True) == 0.05    # ST 5%
    assert get_limit_rate("gem", True) == 0.05     # 创业板 ST 也 5%


def test_to_sina_symbol():
    assert to_sina_symbol("600519") == "sh600519"
    assert to_sina_symbol("000001") == "sz000001"
    assert to_sina_symbol("300750") == "sz300750"
    assert to_sina_symbol("518880") == "sh518880"  # 黄金ETF
    assert to_sina_symbol("159941") == "sz159941"  # 纳指ETF
