"""撮合模块测试：验证 T+1、涨跌停、停牌、成本、滑点。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backtest.broker_sim import (
    PaperBroker,
    compute_limit_prices,
    can_buy_on_open,
    can_sell_on_open,
)


def test_buy_cost_and_cash():
    b = PaperBroker(initial_cash=100000.0, slippage=0.0)
    # 买 100 股 @10 = 1000
    # 佣金 max(1000*2.5e-4, 5) = 5；过户费 1000*1e-5 = 0.01
    # 总支出 = 1000 + 5 + 0.01 = 1005.01
    b.buy("600000", 10.0, 100)
    assert abs(b.cash - (100000 - 1005.01)) < 1e-6


def test_t1_restriction():
    b = PaperBroker(initial_cash=100000.0, slippage=0.0)
    b.buy("600000", 10.0, 100)
    # 当日买入不可卖（available=0）
    assert b.positions["600000"].available == 0
    assert b.sell("600000", 10.0, 100) is None
    # 次日解锁
    b.next_day()
    assert b.positions["600000"].available == 100
    assert b.sell("600000", 10.0, 100) is not None


def test_sell_stamp_tax():
    b = PaperBroker(initial_cash=100000.0, slippage=0.0)
    b.buy("600000", 10.0, 100)
    b.next_day()
    cash_before = b.cash
    b.sell("600000", 10.0, 100)
    # 回款 = 1000 - (佣金 5 + 印花税 0.5 + 过户费 0.01) = 994.49
    assert abs((b.cash - cash_before) - 994.49) < 1e-6


def test_insufficient_cash():
    b = PaperBroker(initial_cash=100.0, slippage=0.0)
    assert b.buy("600000", 10.0, 100) is None  # 需要 1005.01 > 100


def test_limit_price_calc():
    up, down = compute_limit_prices(10.0, 0.10)
    assert up == 11.0
    assert down == 9.0


def test_limit_up_block_buy():
    bar = dict(open=11.0, high=11.0, low=11.0, close=11.0, is_trading=1, prev_close=10.0)
    assert can_buy_on_open(bar, 0.10) is False   # 一字涨停买不进
    assert can_sell_on_open(bar, 0.10) is True   # 涨停能卖出


def test_limit_down_block_sell():
    bar = dict(open=9.0, high=9.0, low=9.0, close=9.0, is_trading=1, prev_close=10.0)
    assert can_sell_on_open(bar, 0.10) is False  # 一字跌停卖不出
    assert can_buy_on_open(bar, 0.10) is True


def test_suspend_block():
    bar = dict(open=10.0, high=10.0, low=10.0, close=10.0, is_trading=0, prev_close=10.0)
    assert can_buy_on_open(bar) is False
    assert can_sell_on_open(bar) is False


def test_slippage():
    b = PaperBroker(initial_cash=100000.0, slippage=0.001)
    b.buy("600000", 10.0, 100)
    # 成交价 = 10 * 1.001 = 10.01（记录在成交流水中）
    assert abs(b.trades[-1]["price"] - 10.01) < 1e-6


def test_t0_etf_recognition():
    """T+0/T+1 品种识别：跨境/黄金 ETF 当日买即可卖；主板股票 T+1。"""
    from backtest.broker_sim import PaperBroker, is_t0_etf

    assert is_t0_etf("513100") is True    # 纳指 ETF（跨境 T+0）
    assert is_t0_etf("518880") is True    # 黄金 ETF（T+0）
    assert is_t0_etf("600519") is False   # 主板股票（T+1）
    assert is_t0_etf("000001") is False   # 主板股票（T+1）

    # T+0 ETF：当日买入当日可卖
    b = PaperBroker(initial_cash=1_000_000.0)
    assert b.buy("513100", 2.0, 1000) is not None
    assert b.positions["513100"].available == 1000  # 当日即解锁
    assert b.sell("513100", 2.0, 1000) is not None   # 当日卖出成功

    # T+1 股票：当日买入不可卖，次日解锁
    b2 = PaperBroker(initial_cash=1_000_000.0)
    assert b2.buy("600519", 1700.0, 100) is not None
    assert b2.positions["600519"].available == 0    # 当日锁定
    assert b2.sell("600519", 1700.0, 100) is None   # 当日卖被拒
    b2.next_day()
    assert b2.positions["600519"].available == 100  # 次日解锁
    assert b2.sell("600519", 1700.0, 100) is not None
