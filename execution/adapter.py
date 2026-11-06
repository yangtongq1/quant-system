"""
交易执行适配层（BrokerAdapter 抽象接口）

设计目标：对上层策略暴露统一下单/撤单/查询接口，屏蔽底层（回测撮合 /
SuperMind 仿真 / 未来券商 QMT/PTrade）差异，切换执行端不改策略代码。

智谱需实现两个子类：
- execution/paper_broker.py  : 回测/自建模拟撮合（可复用 backtest/broker_sim.PaperBroker）
- execution/supermind_broker.py : 对接同花顺 SuperMind 仿真账户（tick_trade_api）
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class BrokerAdapter(ABC):
    """统一交易接口。返回 order_id（字符串），实现类自行生成。"""

    @abstractmethod
    def buy(self, code: str, price: float, volume: int) -> str:
        """买入。price<=0 表示市价单。返回订单号。"""

    @abstractmethod
    def sell(self, code: str, price: float, volume: int) -> str:
        """卖出。返回订单号。"""

    @abstractmethod
    def cancel(self, order_id: str) -> bool:
        """撤单。返回是否成功。"""

    @abstractmethod
    def get_orders(self) -> list:
        """查询订单列表。"""

    @abstractmethod
    def get_trades(self) -> list:
        """查询成交流水。"""

    @abstractmethod
    def get_positions(self) -> list:
        """查询持仓。"""

    @abstractmethod
    def get_account(self) -> dict:
        """查询账户资金（可用资金/总资产等）。"""
