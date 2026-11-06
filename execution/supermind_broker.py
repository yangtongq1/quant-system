"""
SuperMind 仿真账户适配器（M5 执行层）

对接同花顺 SuperMind tick_trade_api：
    from tick_trade_api import TradeAPI
    trade_api = TradeAPI('模拟资金账号', order_policy=LimitPolicy)
    trade_api.order(symbol='000001.SZ', amount=100, price=10, side=SIDE.BUY)

前置条件（用户侧）：
1. 下载 SuperMind 体验版（官方 quant.10jqka.com.cn）
2. 同花顺账号登录客户端
3. 客户端内添加「仿真模拟账号」
4. 保持客户端登录状态

SDK 未安装 / 未登录时：import 或初始化失败 → 优雅降级为 DryRun 模式
（订单只入本地库并标记 DRY_RUN，不发真实委托），保证策略代码可先行调试。
"""

from __future__ import annotations

import os

from execution.adapter import BrokerAdapter


class SuperMindBroker(BrokerAdapter):
    """同花顺 SuperMind 仿真账户执行器。"""

    def __init__(self, account: str | None = None, dry_run_on_fail: bool = True):
        self.account = account or os.environ.get("SUPERMIND_ACCOUNT", "")
        self.api = None
        self.dry_run = False
        self.orders: list[dict] = []

        try:
            from tick_trade_api import TradeAPI  # noqa: F401
            if not self.account:
                raise ValueError("SUPERMIND_ACCOUNT 未配置")
            # LimitPolicy / SIDE 在 order 时导入（避免模块级硬依赖）
            self._TradeAPI = TradeAPI
            self.api = self._init_api()
        except Exception as e:  # noqa: BLE001
            if dry_run_on_fail:
                self.dry_run = True
                print(f"[supermind] 初始化失败，进入 DryRun 模式: {type(e).__name__} {str(e)[:120]}")
            else:
                raise

    def _init_api(self):
        """初始化 TradeAPI（客户端须登录）。"""
        from tick_trade_api import TradeAPI, LimitPolicy
        return TradeAPI(self.account, order_policy=LimitPolicy)

    def _symbol(self, code: str) -> str:
        """600519 → 600519.SH；000001 → 000001.SZ。"""
        if code.startswith(("6", "9", "5")):
            return f"{code}.SH"
        if code.startswith(("0", "3", "1")):
            return f"{code}.SZ"
        return f"{code}.BJ"

    # ---- BrokerAdapter 接口 ----
    def buy(self, code: str, price: float, volume: int) -> str:
        return self._order(code, "buy", price, volume)

    def sell(self, code: str, price: float, volume: int) -> str:
        return self._order(code, "sell", price, volume)

    def _order(self, code: str, side: str, price: float, volume: int) -> str:
        import time
        order_id = f"SM-{int(time.time() * 1000)}-{code}"
        if self.dry_run or self.api is None:
            self.orders.append({"order_id": order_id, "code": code, "side": side,
                                "price": price, "volume": volume, "status": "DRY_RUN"})
            print(f"[supermind][DRY_RUN] {side} {code} {volume}@{price}")
            return order_id
        try:
            from tick_trade_api import SIDE
            side_enum = SIDE.BUY if side == "buy" else SIDE.SELL
            self.api.order(symbol=self._symbol(code), amount=volume, price=price, side=side_enum)
            self.orders.append({"order_id": order_id, "code": code, "side": side,
                                "price": price, "volume": volume, "status": "SUBMITTED"})
            return order_id
        except Exception as e:  # noqa: BLE001
            self.orders.append({"order_id": order_id, "code": code, "side": side,
                                "price": price, "volume": volume, "status": "REJECTED",
                                "reason": str(e)[:120]})
            return order_id

    def cancel(self, order_id: str) -> bool:
        if self.dry_run or self.api is None:
            return False
        try:
            self.api.cancel_order(order_id)
            return True
        except Exception:  # noqa: BLE001
            return False

    def get_orders(self) -> list:
        return list(self.orders)

    def get_trades(self) -> list:
        if self.dry_run or self.api is None:
            return []
        try:
            return list(self.api.entrust)
        except Exception:  # noqa: BLE001
            return []

    def get_positions(self) -> list:
        if self.dry_run or self.api is None:
            return []
        try:
            return list(self.api.position)
        except Exception:  # noqa: BLE001
            return []

    def get_account(self) -> dict:
        if self.dry_run or self.api is None:
            return {"dry_run": True, "account": self.account}
        try:
            return dict(self.api.account)
        except Exception:  # noqa: BLE001
            return {}
