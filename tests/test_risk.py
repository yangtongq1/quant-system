"""
风控 + 压力测试
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from risk.manager import RiskManager, RiskRules
from risk.stress import run_stress_tests, hedge_failure_test, scenario_replay


def _portfolio(cash=500_000.0, positions=None):
    positions = positions or {}
    total = cash + sum(p["volume"] * p.get("avg_cost", 10.0) for p in positions.values())
    return {"cash": cash, "positions": positions, "total_asset": total}


def test_pre_trade_position_limit():
    """事前：单标的持仓上限拦截。"""
    rm = RiskManager(RiskRules(max_position_pct=0.20, max_order_pct=0.30))
    pf = _portfolio(cash=1_000_000)
    # 单笔 20 万（20% 总资产）：单笔上限 30% 通过，持仓上限 20% 边界通过
    ok, _ = rm.pre_trade_check(pf, "600519", "buy", 100.0, 2000)
    assert ok
    # 单笔 30 万（30%）超持仓上限 20% → 拒绝
    ok, reason = rm.pre_trade_check(pf, "600519", "buy", 100.0, 3000)
    assert not ok
    assert "上限" in reason


def test_pre_trade_cash_check():
    """事前：资金校验。"""
    rm = RiskManager(RiskRules(max_order_pct=0.5, max_position_pct=0.9))
    # 现金 8 千 + 持仓 9.2 万（total 10 万），单笔 1.5 万：不超单笔上限（5 万），
    # 不超持仓上限，但现金只有 8 千 → 资金不足拦截
    pf = _portfolio(cash=8_000, positions={
        "600000": {"volume": 9200, "avg_cost": 10.0},
    })
    ok, reason = rm.pre_trade_check(pf, "600519", "buy", 75.0, 200)  # 需 1.5 万 > 现金 8 千
    assert not ok
    assert "资金" in reason


def test_pre_trade_price_deviation():
    """事前：异常价格拦截（乌龙指防护）。"""
    rm = RiskManager(RiskRules(max_order_pct=0.9, max_position_pct=0.9))
    pf = _portfolio(cash=1_000_000)
    # 参考价 10 元，限价 15 元（偏离 50%）→ 拒绝
    ok, reason = rm.pre_trade_check(pf, "600519", "buy", 15.0, 1000, ref_price=10.0)
    assert not ok
    assert "偏离" in reason


def test_frequency_limit():
    """事中：单日订单频率拦截。"""
    rm = RiskManager(RiskRules(max_orders_per_day=3))
    results = [rm.check_frequency("2026-11-06")[0] for _ in range(4)]
    assert results == [True, True, True, False]


def test_events_logged():
    """风控事件留痕（append-only）。"""
    rm = RiskManager()
    pf = _portfolio(cash=1_000_000)
    rm.pre_trade_check(pf, "600519", "buy", 100.0, 10_000)  # 超限 → 拒绝
    assert len(rm.events) == 1
    assert rm.events[0]["type"] == "pre_trade_reject"


def test_post_drawdown_alert():
    """事后：回撤破硬约束告警。"""
    rm = RiskManager(RiskRules(max_drawdown=0.10))
    eq = pd.Series([100.0, 105.0, 90.0, 95.0, 100.0], index=pd.date_range("2025-01-01", periods=5))
    alerts = rm.post_check(eq)
    assert any("回撤" in a for a in alerts)


def test_scenario_replay():
    """情景回放：2015 股灾区间净值回撤计算。"""
    dates = pd.date_range("2015-06-01", "2015-10-31", freq="B")
    rng = np.random.default_rng(0)
    # 构造一段从 100 跌到 70 的行情
    n = len(dates)
    eq = pd.Series(np.linspace(100, 70, n) + rng.normal(0, 1, n), index=dates)
    r = scenario_replay(eq, {"label": "2015 股灾", "start": "2015-06-15", "end": "2015-09-30"})
    assert r["status"] == "ok"
    assert r["return"] < 0
    assert r["max_drawdown"] < 0


def test_run_stress_tests():
    """全情景回放报告表。"""
    dates = pd.date_range("2015-01-01", "2021-12-31", freq="B")
    rng = np.random.default_rng(1)
    eq = pd.Series(100 * np.cumprod(1 + rng.normal(-0.0002, 0.02, len(dates))), index=dates)
    df = run_stress_tests(eq)
    assert len(df) == 4  # 四个内置情景
    assert set(df["status"]) <= {"ok", "no_data"}


def test_hedge_failure():
    """对冲失效测试：构造危机时同跌数据，相关性应检测为正。"""
    dates = pd.date_range("2020-01-01", "2020-06-30", freq="B")
    rng = np.random.default_rng(2)
    n = len(dates)
    # 正常期：三资产独立
    stock = 100 * np.cumprod(1 + rng.normal(0.0005, 0.015, n))
    gold = 100 * np.cumprod(1 + rng.normal(0.0005, 0.008, n))
    nasdaq = 100 * np.cumprod(1 + rng.normal(0.0007, 0.018, n))
    # 疫情期（2020-02-03 ~ 2020-03-31）：共同危机因子驱动同跌（真实危机模式）
    crisis = pd.Series(np.where((dates >= "2020-02-03") & (dates <= "2020-03-31"), 1.0, 0.0), index=dates)
    common_shock = crisis * rng.normal(-0.018, 0.012, n)   # 共同负向冲击（压过个体噪声）
    stock = stock * np.cumprod(1 + common_shock)
    nasdaq = nasdaq * np.cumprod(1 + 1.3 * common_shock)
    prices = pd.DataFrame({"stock": stock, "gold": gold, "nasdaq": nasdaq}, index=dates)
    df = hedge_failure_test(prices)
    covid_row = df[df["scenario"] == "2020_covid"].iloc[0]
    assert covid_row["status"] == "ok"
    assert covid_row["nasdaq_stock_corr"] > 0.3, "危机期纳指-A股相关性应为正（对冲失效）"
