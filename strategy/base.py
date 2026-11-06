"""
策略基类（核心接口骨架）

设计要点：
- 回测与模拟盘共用同一套策略代码，通过 Context 下单，禁止两套逻辑分叉。
- 信号通过 context.buy / context.sell 发出，内部走 BrokerAdapter。
- 回测引擎中信号延迟到 T+1 开盘成交（杜绝未来函数）；模拟盘立即执行。
- 风控在 BrokerAdapter 之前强制校验，策略无权绕过（见 risk/manager.py）。
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class Context:
    """策略运行上下文：持有账户/行情快照，提供下单入口。"""

    def __init__(self, broker, defer_execution: bool = False):
        self.broker = broker  # BrokerAdapter 实现（回测或 SuperMind）
        self.portfolio = None  # 由引擎注入当前账户状态
        self.defer_execution = defer_execution  # 回测=True 信号延迟 T+1；模拟盘=False 立即执行
        self._pending_orders: list[dict] = []   # 待执行信号队列

    def buy(self, code: str, price: float, volume: int, limit_rate: float = 0.10):
        """发出买入信号。

        回测模式（defer_execution=True）：信号入队，T+1 开盘由引擎撮合。
        模拟盘模式：经风控校验后立即执行。
        price<=0 表示市价单（回测中按次日开盘价撮合）。
        """
        order = {"code": code, "side": "buy", "price": price,
                 "volume": int(volume), "limit_rate": limit_rate}
        if self.defer_execution:
            self._pending_orders.append(order)
            return None
        return self.broker.buy(code, price, volume)

    def sell(self, code: str, price: float, volume: int, limit_rate: float = 0.10):
        """发出卖出信号（语义同 buy）。"""
        order = {"code": code, "side": "sell", "price": price,
                 "volume": int(volume), "limit_rate": limit_rate}
        if self.defer_execution:
            self._pending_orders.append(order)
            return None
        return self.broker.sell(code, price, volume)

    def pop_pending_orders(self) -> list[dict]:
        """引擎取走待执行信号队列。"""
        orders, self._pending_orders = self._pending_orders, []
        return orders


class Strategy(ABC):
    """策略基类。子类至少实现 init 与 on_bar。"""

    @abstractmethod
    def init(self, context: Context):
        """初始化参数（回测开始时调用一次）。"""

    def before_trading(self, context: Context):
        """盘前（可选）。"""

    @abstractmethod
    def on_bar(self, context: Context, bar: dict):
        """核心：每个交易日/每根 bar 生成信号。"""

    def after_trading(self, context: Context):
        """盘后（可选）。"""
