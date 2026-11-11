"""execute_orders_on_channel 单元测试（外部通道执行循环）。

覆盖：先卖后买顺序、ETF 腿放宽规则放行、个股严规则拦截、限价缓冲。
用本地 PaperBrokerAdapter 顶替外部通道（接口一致，不依赖 QMT 客户端）。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from execution.paper_broker import PaperBrokerAdapter
from execution.paper_engine import execute_orders_on_channel
from risk.manager import RiskManager, RiskRules


class _ScriptedBroker(PaperBrokerAdapter):
    """脚本化通道：记录调用顺序 + 可抛异常。"""

    def __init__(self, fail_codes: set[str] | None = None):
        super().__init__(initial_cash=10_000_000.0)
        self.calls: list[tuple[str, str, float, int]] = []
        self.fail_codes = fail_codes or set()

    def buy(self, code, price, volume):
        self.calls.append(("buy", code, price, volume))
        if code in self.fail_codes:
            raise RuntimeError("模拟通道下单异常")
        return f"B-{len(self.calls)}"

    def sell(self, code, price, volume):
        self.calls.append(("sell", code, price, volume))
        if code in self.fail_codes:
            raise RuntimeError("模拟通道下单异常")
        return f"S-{len(self.calls)}"

    def get_account(self):
        return {"available_cash": 10_000_000.0, "total_value": 10_000_000.0}

    def get_positions(self):
        return [
            {"code": "600000", "volume": 10_000, "available": 10_000, "avg_cost": 8.0},
            {"code": "518880", "volume": 20_000, "available": 20_000, "avg_cost": 8.0},
        ]


def test_sell_before_buy_order():
    broker = _ScriptedBroker()
    orders = [
        {"code": "600000", "side": "buy", "volume": 1000, "price": 8.0},
        {"code": "518880", "side": "sell", "volume": 5000, "price": 8.0},
    ]
    rm = RiskManager(RiskRules())
    report = execute_orders_on_channel(broker, orders, rm, rm.rules)
    # 先卖后买：第一笔调用必须是 sell
    assert broker.calls[0][0] == "sell"
    assert broker.calls[1][0] == "buy"
    assert all(r["status"] == "SUBMITTED" for r in report)


def test_etf_leg_relaxed_rules():
    """ETF 腿（黄金 25% 仓位）在放宽规则下放行；同样市值在个股严规则下被拒。"""
    broker = _ScriptedBroker()
    # 20000股×8元=160,000... 需要 ETF 腿更大市值触发规则差异：
    # 放宽规则 position 0.75 → 25% 仓位 ETF 放行
    orders = [
        {"code": "518880", "side": "buy", "volume": 300_000, "price": 8.0},  # 240万 = 24%
    ]
    rm = RiskManager(RiskRules())
    report = execute_orders_on_channel(broker, orders, rm, rm.rules)
    assert report[0]["status"] == "SUBMITTED"

    # 同样一笔在个股严规则（position 0.20）下必被拒
    broker2 = _ScriptedBroker()
    orders2 = [
        {"code": "600000", "side": "buy", "volume": 300_000, "price": 8.0},  # 240万 = 24%
    ]
    rm2 = RiskManager(RiskRules())
    report2 = execute_orders_on_channel(broker2, orders2, rm2, rm2.rules)
    assert report2[0]["status"] == "REJECTED"
    assert "单笔金额" in report2[0]["reason"] or "市值占比" in report2[0]["reason"]


def test_price_buffer_applied():
    """限价缓冲：买入加 1%、卖出减 1%。"""
    broker = _ScriptedBroker()
    orders = [
        {"code": "600000", "side": "buy", "volume": 1000, "price": 10.0},
        {"code": "000001", "side": "sell", "volume": 1000, "price": 10.0},
    ]
    rm = RiskManager(RiskRules())
    report = execute_orders_on_channel(broker, orders, rm, rm.rules)
    # 先卖后买重排：report[0]=000001 卖出（9.89），report[1]=600000 买入（10.11）
    # 取整规则：买入 ceil 到分（+0.005 后 round），卖出 floor 到分
    by_code = {(r["code"], r["side"]): r for r in report}
    assert by_code[("600000", "buy")]["price"] == 10.11
    assert by_code[("000001", "sell")]["price"] == 9.89


def test_channel_exception_recorded():
    """通道下单异常 → REJECTED + 原因留痕，不中断后续订单。"""
    broker = _ScriptedBroker(fail_codes={"600000"})
    orders = [
        {"code": "600000", "side": "buy", "volume": 1000, "price": 8.0},
        {"code": "000001", "side": "buy", "volume": 1000, "price": 10.0},
    ]
    rm = RiskManager(RiskRules())
    report = execute_orders_on_channel(broker, orders, rm, rm.rules)
    assert report[0]["status"] == "REJECTED"
    assert "RuntimeError" in report[0]["reason"]
    assert report[1]["status"] == "SUBMITTED"
