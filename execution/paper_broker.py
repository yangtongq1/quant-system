"""
PaperBroker 适配器（M5 执行层）

复用 backtest/broker_sim.PaperBroker 撮合逻辑，适配 BrokerAdapter 统一接口。
风控校验在执行前强制进行（RiskManager 注入，策略无权绕过）。
"""

from __future__ import annotations

import itertools
import uuid

from backtest.broker_sim import PaperBroker
from execution.adapter import BrokerAdapter


class PaperBrokerAdapter(BrokerAdapter):
    """本地模拟盘执行器（BrokerAdapter 实现）。

    与回测共用 PaperBroker 撮合核心（红线 7：回测/模拟盘共用策略代码）。
    """

    def __init__(self, paper: PaperBroker | None = None, initial_cash: float = 1_000_000.0,
                 risk_manager=None):
        self.paper = paper or PaperBroker(initial_cash=initial_cash)
        self.risk = risk_manager
        self.orders: list[dict] = []
        self._id = itertools.count(1)

    def _next_order_id(self) -> str:
        return f"PB-{next(self._id):06d}-{uuid.uuid4().hex[:6]}"

    def _check_risk(self, code: str, side: str, price: float, volume: int) -> tuple[bool, str]:
        """事前风控（独立于策略强制执行）。"""
        if self.risk is None:
            return True, ""
        return self.risk.pre_trade_check(self._portfolio(), code, side, price, volume)

    def _portfolio(self) -> dict:
        positions = {
            code: {"volume": pos.volume, "available": pos.available, "avg_cost": pos.avg_cost}
            for code, pos in self.paper.positions.items()
        }
        return {"cash": self.paper.cash, "positions": positions,
                "total_asset": self.paper.cash + sum(
                    p["volume"] * p["avg_cost"] for p in positions.values())}

    # ---- BrokerAdapter 接口 ----
    def buy(self, code: str, price: float, volume: int) -> str:
        order_id = self._next_order_id()
        ok, reason = self._check_risk(code, "buy", price, volume)
        if not ok:
            self.orders.append({"order_id": order_id, "code": code, "side": "buy",
                                "price": price, "volume": volume, "status": "REJECTED",
                                "reason": reason})
            return order_id
        fill = self.paper.buy(code, price, volume)
        status = "FILLED" if fill else "REJECTED"
        self.orders.append({"order_id": order_id, "code": code, "side": "buy",
                            "price": price, "volume": volume, "status": status})
        return order_id

    def sell(self, code: str, price: float, volume: int) -> str:
        order_id = self._next_order_id()
        ok, reason = self._check_risk(code, "sell", price, volume)
        if not ok:
            self.orders.append({"order_id": order_id, "code": code, "side": "sell",
                                "price": price, "volume": volume, "status": "REJECTED",
                                "reason": reason})
            return order_id
        fill = self.paper.sell(code, price, volume)
        status = "FILLED" if fill else "REJECTED"
        self.orders.append({"order_id": order_id, "code": code, "side": "sell",
                            "price": price, "volume": volume, "status": status})
        return order_id

    def cancel(self, order_id: str) -> bool:
        for o in self.orders:
            if o["order_id"] == order_id and o["status"] in ("NEW", "SUBMITTED"):
                o["status"] = "CANCELLED"
                return True
        return False

    def get_orders(self) -> list:
        return list(self.orders)

    def get_trades(self) -> list:
        return list(self.paper.trades)

    def get_positions(self) -> list:
        return [
            {"code": code, "volume": pos.volume, "available": pos.available,
             "avg_cost": pos.avg_cost}
            for code, pos in self.paper.positions.items()
        ]

    def get_account(self) -> dict:
        return {
            "cash": self.paper.cash,
            "total_asset": self._portfolio()["total_asset"],
            "initial_cash": self.paper.initial_cash,
        }
