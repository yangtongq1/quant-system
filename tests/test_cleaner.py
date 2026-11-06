"""数据清洗模块测试：验证列校验、去重、停牌标记、复权。"""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from data.cleaner import clean_daily_bars, adjust_price


def _make_df(dates, closes, volumes):
    n = len(dates)
    return pd.DataFrame({
        "date": dates,
        "open": closes,
        "high": [c + 1 for c in closes],
        "low": [c - 1 for c in closes],
        "close": closes,
        "volume": volumes,
    })


def test_missing_cols_raise():
    df = pd.DataFrame({"date": ["2024-01-01"], "close": [10.0]})
    try:
        clean_daily_bars(df)
        assert False, "应抛异常"
    except ValueError:
        pass


def test_sort_and_dedup():
    df = _make_df(
        ["2024-01-03", "2024-01-01", "2024-01-01"],
        [10.0, 10.0, 9.0],
        [100, 100, 100],
    )
    out = clean_daily_bars(df)
    assert len(out) == 2
    assert list(out["date"]) == list(pd.to_datetime(["2024-01-01", "2024-01-03"]))
    assert out.iloc[0]["close"] == 9.0  # 去重保留最后一条


def test_suspend_mark():
    df = _make_df(
        ["2024-01-01", "2024-01-02"],
        [10.0, 10.0],
        [100, 0],  # 第二日无成交 = 停牌
    )
    out = clean_daily_bars(df)
    assert out.iloc[0]["is_trading"] == 1
    assert out.iloc[1]["is_trading"] == 0


def test_negative_price_raise():
    df = _make_df(["2024-01-01"], [10.0], [100])
    df.loc[0, "close"] = -5.0
    try:
        clean_daily_bars(df, strict=True)
        assert False, "应抛异常"
    except ValueError:
        pass


def test_adjust_qfq():
    df = _make_df(["2024-01-01", "2024-01-02"], [10.0, 5.0], [100, 100])
    df["adj_factor"] = [1.0, 0.5]
    out = clean_daily_bars(df)
    qfq = adjust_price(out, "qfq")
    # 前复权：latest factor = 0.5
    # 第一天 close = 10 * (1.0/0.5) = 20；第二天 close = 5 * (0.5/0.5) = 5
    assert abs(qfq.iloc[0]["close"] - 20.0) < 1e-6
    assert abs(qfq.iloc[1]["close"] - 5.0) < 1e-6


def test_adjust_hfq():
    df = _make_df(["2024-01-01", "2024-01-02"], [10.0, 5.0], [100, 100])
    df["adj_factor"] = [1.0, 0.5]
    out = clean_daily_bars(df)
    hfq = adjust_price(out, "hfq")
    # 后复权：close * adj_factor
    # 第一天 10*1.0=10；第二天 5*0.5=2.5
    assert abs(hfq.iloc[0]["close"] - 10.0) < 1e-6
    assert abs(hfq.iloc[1]["close"] - 2.5) < 1e-6
