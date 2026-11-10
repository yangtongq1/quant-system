"""
SuperMind 仿真账户适配器（M5 执行层 · 官方文档对齐版）

对接同花顺 SuperMind tick_trade_api（官方文档：
https://quant.10jqka.com.cn/research/users/376557922/f4989e80430f214ae22707e64e44a314.html）

    from tick_trade_api.api import TradeAPI
    trade_api = TradeAPI(account_id='69271711')   # 填入客户端已登录的资金账号
    portfolio = trade_api.portfolio               # NameDict: available_cash/market_value/total_value
    positions = trade_api.positions               # dict: 代码 -> NameDict
    trade_api.order(symbol='000001.SZ', amount=100, price=10, side=SIDE.BUY)   # 限价单
    trade_api.cancel_order('107828')               # 撤单

前置条件（用户侧，缺一不可）：
1. 下载 SuperMind 客户端（Windows）：官方 quant.10jqka.com.cn，
   仿真版：http://zjcmpp.hexin.com.cn/download/lhjy3/Free/THS_Qstudio_Setup_Mfjy.exe
2. 同花顺账号登录客户端
3. 客户端内创建「仿真模拟账户」，并保持该资金账号处于登录状态
4. SDK（tick_trade_api）仅随客户端研究环境内置，不发布到 PyPI

凭证（二选一，读 .env）：
- SUPERMIND_ACCOUNT   客户端已登录的仿真资金账号（如 '69271711'）—— 正式交易通道
- SUPERMIND_API_KEY   sk- 形式的平台密钥（如 sk-qmt...）—— 目前仅作登记，
  SuperMind 交易接口不消费此密钥；留作未来平台开放 HTTP 网关时使用

SDK 未安装 / 未配置账号 / 客户端未登录：初始化失败 → 优雅降级 DryRun 模式
（订单只入本地库并标记 DRY_RUN，不发真实委托），保证策略代码可先行调试。
"""

from __future__ import annotations

import os
from datetime import datetime

from core.config import load_env
from execution.adapter import BrokerAdapter

# .env 位于项目根（含 SUPERMIND_ACCOUNT / SUPERMIND_API_KEY），随取随加载
load_env(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))


class SuperMindBroker(BrokerAdapter):
    """同花顺 SuperMind 仿真账户执行器（官方 tick_trade_api 协议）。"""

    def __init__(self, account: str | None = None, dry_run_on_fail: bool = True):
        self.account = account or os.environ.get("SUPERMIND_ACCOUNT", "")
        self.api_key = os.environ.get("SUPERMIND_API_KEY", "")  # 登记，暂不用于下单
        self.api = None
        self.dry_run = False
        self.orders: list[dict] = []
        self.last_error: str = ""

        if not self.account:
            self._fail("SUPERMIND_ACCOUNT 未配置（.env），无法连接真实仿真账户", dry_run_on_fail)
            return

        try:
            from tick_trade_api.api import TradeAPI  # 官方路径：tick_trade_api.api
            self._TradeAPI = TradeAPI
            self.api = self._init_api()
        except ImportError:
            self._fail("tick_trade_api 未安装（SDK 仅随 SuperMind Windows 客户端内置，"
                       "PyPI 无此包）", dry_run_on_fail)
        except Exception as e:  # noqa: BLE001
            self._fail(f"TradeAPI 初始化失败: {type(e).__name__} {str(e)[:150]} "
                       f"（检查客户端是否登录、资金账号是否正确）", dry_run_on_fail)

    # ------------------------------------------------------------------
    def _fail(self, msg: str, dry_run_on_fail: bool):
        self.last_error = msg
        if dry_run_on_fail:
            self.dry_run = True
            print(f"[supermind] {msg} → 进入 DryRun 模式（订单仅本地记录，不发真实委托）")
        else:
            raise RuntimeError(msg)

    def _init_api(self):
        """初始化 TradeAPI（客户端须已登录该资金账号）。默认限价单策略。"""
        try:
            from tick_trade_api import LimitPolicy
            return self._TradeAPI(account_id=self.account, order_policy=LimitPolicy)
        except ImportError:
            # 部分版本 LimitPolicy 在顶层包
            return self._TradeAPI(account_id=self.account)

    def _symbol(self, code: str) -> str:
        """600519 → 600519.SH；000001 → 000001.SZ；其余 → .BJ。"""
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
        order_id = f"SM-{datetime.now().strftime('%Y%m%d%H%M%S%f')[:-3]}-{code}"
        if self.dry_run or self.api is None:
            self.orders.append({"order_id": order_id, "code": code, "side": side,
                                "price": price, "volume": volume, "status": "DRY_RUN"})
            print(f"[supermind][DRY_RUN] {side} {code} {volume}@{price}")
            return order_id
        try:
            from tick_trade_api import SIDE
            side_enum = SIDE.BUY if side == "buy" else SIDE.SALE
            # 限价单：price>0 传价格；price<=0 走最新价下单（不传 price）
            if price and price > 0:
                self.api.order(symbol=self._symbol(code), amount=int(volume),
                               price=float(price), side=side_enum)
            else:
                self.api.order(symbol=self._symbol(code), amount=int(volume), side=side_enum)
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
        """当日委托流水（entrust）。"""
        if self.dry_run or self.api is None:
            return []
        try:
            return list(self.api.entrust)
        except Exception:  # noqa: BLE001
            return []

    def get_positions(self) -> list:
        """持仓（positions：dict[代码, NameDict] → 列表化）。"""
        if self.dry_run or self.api is None:
            return []
        try:
            pos = self.api.positions  # 网络波动可能超时，官方建议重试 3 次
            for _ in range(3):
                try:
                    pos = self.api.positions
                    break
                except Exception:  # noqa: BLE001
                    continue
            return list(pos.values()) if isinstance(pos, dict) else list(pos)
        except Exception:  # noqa: BLE001
            return []

    def get_account(self) -> dict:
        """账户资金（portfolio：NameDict → dict）。"""
        if self.dry_run or self.api is None:
            return {"dry_run": True, "account": self.account,
                    "error": self.last_error or "SDK 未安装"}
        try:
            pf = self.api.portfolio
            keys = ("available_cash", "market_value", "frozen_cash", "total_value")
            out = {}
            for k in keys:
                try:
                    out[k] = pf[k]
                except Exception:  # noqa: BLE001
                    pass
            out["account"] = self.account
            return out
        except Exception:  # noqa: BLE001
            return {"account": self.account, "error": "portfolio 查询失败"}

    def status(self) -> dict:
        """连接状态一览（控制台/诊断用）。"""
        return {
            "mode": "DRY_RUN" if self.dry_run else "LIVE",
            "account": self.account or "(未配置)",
            "api_key_registered": bool(self.api_key),
            "sdk_installed": not self.dry_run or "tick_trade_api" in str(self.last_error),
            "last_error": self.last_error or "",
        }
