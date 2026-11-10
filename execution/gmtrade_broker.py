"""
掘金量化（MyQuant）仿真账户适配器（M5 执行层 · 免费仿真路线）

掘金仿真 = 网页注册即用的仿真撮合柜台（无券商、无资产门槛、无客户端要求）：
    注册：https://sim.myquant.cn （或 www.myquant.cn → 仿真交易）
    → 登录 → 新建仿真账户（选「股票」类型，设初始资金）→ 得到账户 ID
    → 个人中心 → 安全设置 → 获取 token

SDK：pip install gmtrade（注意：只支持 Python 3.6–3.10，需用 py310 运行）
    from gmtrade.api import *
    set_token("你的token")                      # 掘金身份识别
    set_endpoint("api.myquant.cn:9000")         # 官方仿真服务地址
    a = account(account_id="xxxx"); login(a)     # 登录仿真账户
    order_volume(symbol="SHSE.600000", volume=100,
                 side=OrderSide_Buy, order_type=OrderType_Limit, price=11)

前置条件（用户侧，全部免费）：
1. sim.myquant.cn 注册掘金账号
2. 网页上新建「股票」仿真账户（设初始资金，如 1000000）
3. 个人中心复制 token 和账户 ID 到 .env（GMTRADE_TOKEN / GMTRADE_ACCOUNT）
4. 系统装有 Python 3.10（gmtrade 仅支持 cp36-cp310；项目主力 Python 3.13 跑不了该包）

未配置 / SDK 缺失：优雅降级 DryRun（订单只入本地库，不发委托）。
"""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime

from core.config import load_env
from execution.adapter import BrokerAdapter

load_env(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

# gmtrade 只支持 py310 及以下；主环境（3.13）没有该包时的回退解释器
_PY310 = r"C:\Users\admin\py310\python.exe"


def _gmtrade_available() -> bool:
    """当前解释器能否 import gmtrade。"""
    try:
        import gmtrade  # noqa: F401
        return True
    except ImportError:
        return False


class GmTradeBroker(BrokerAdapter):
    """掘金量化仿真账户执行器（gmtrade 官方协议）。"""

    def __init__(self, token: str | None = None, account_id: str | None = None,
                 endpoint: str = "api.myquant.cn:9000",
                 dry_run_on_fail: bool = True):
        self.token = token or os.environ.get("GMTRADE_TOKEN", "")
        self.account_id = account_id or os.environ.get("GMTRADE_ACCOUNT", "")
        self.endpoint = endpoint
        self.dry_run = False
        self.orders: list[dict] = []
        self.last_error: str = ""
        self._logged_in = False

        if not self.token or not self.account_id:
            self._fail("GMTRADE_TOKEN / GMTRADE_ACCOUNT 未配置（.env）——"
                       "到 sim.myquant.cn 注册并新建仿真账户后获取", dry_run_on_fail)
            return

        try:
            from gmtrade.api import set_token, set_endpoint, account, login
            set_token(self.token)
            set_endpoint(self.endpoint)
            a = account(account_id=self.account_id)
            login(a)
            self._logged_in = True
        except ImportError:
            self._fail(f"gmtrade 未安装（仅支持 Python 3.6–3.10；"
                       f"当前解释器 {sys.version.split()[0]}）。"
                       f"装法：用 py310 安装并用它运行", dry_run_on_fail)
        except Exception as e:  # noqa: BLE001
            self._fail(f"掘金仿真登录失败: {type(e).__name__} {str(e)[:150]} "
                       f"（检查 token/账户ID 是否有效）", dry_run_on_fail)

    # ------------------------------------------------------------------
    def _fail(self, msg: str, dry_run_on_fail: bool):
        self.last_error = msg
        if dry_run_on_fail:
            self.dry_run = True
            print(f"[gmtrade] {msg} → 进入 DryRun 模式（订单仅本地记录）")
        else:
            raise RuntimeError(msg)

    def _symbol(self, code: str) -> str:
        """600519 → SHSE.600519；000001 → SZSE.000001；其余 → BJSE.。"""
        if code.startswith(("6", "9", "5")):
            return f"SHSE.{code}"
        if code.startswith(("0", "3", "1")):
            return f"SZSE.{code}"
        return f"BJSE.{code}"

    # ---- BrokerAdapter 接口 ----
    def buy(self, code: str, price: float, volume: int) -> str:
        return self._order(code, "buy", price, volume)

    def sell(self, code: str, price: float, volume: int) -> str:
        return self._order(code, "sell", price, volume)

    def _order(self, code: str, side: str, price: float, volume: int) -> str:
        order_id = f"GM-{datetime.now().strftime('%Y%m%d%H%M%S%f')[:-3]}-{code}"
        if self.dry_run or not self._logged_in:
            self.orders.append({"order_id": order_id, "code": code, "side": side,
                                "price": price, "volume": volume, "status": "DRY_RUN"})
            print(f"[gmtrade][DRY_RUN] {side} {code} {volume}@{price}")
            return order_id
        try:
            from gmtrade.api import order_volume
            from gmtrade.enum import OrderSide_Buy, OrderSide_Sell, OrderType_Limit, OrderType_Market
            if price and price > 0:
                otype, px = OrderType_Limit, float(price)
            else:
                otype, px = OrderType_Market, 0.0
            o = order_volume(symbol=self._symbol(code), volume=int(volume),
                             side=OrderSide_Buy if side == "buy" else OrderSide_Sell,
                             order_type=otype, price=px,
                             account=self.account_id)
            oid = getattr(o, "ord_ord_xno", None) or getattr(o, "ord_id", None) or order_id
            self.orders.append({"order_id": order_id, "xt_id": str(oid), "code": code,
                                "side": side, "price": price, "volume": volume,
                                "status": "SUBMITTED"})
            return order_id
        except Exception as e:  # noqa: BLE001
            self.orders.append({"order_id": order_id, "code": code, "side": side,
                                "price": price, "volume": volume, "status": "REJECTED",
                                "reason": str(e)[:120]})
            return order_id

    def cancel(self, order_id: str) -> bool:
        if self.dry_run or not self._logged_in:
            return False
        try:
            from gmtrade.api import cancel_order
            cancel_order(order_id, account=self.account_id)
            return True
        except Exception:  # noqa: BLE001
            return False

    def get_orders(self) -> list:
        if self.dry_run or not self._logged_in:
            return []
        try:
            from gmtrade.api import get_unfinished_orders
            return list(get_unfinished_orders(account=self.account_id) or [])
        except Exception:  # noqa: BLE001
            return []

    def get_trades(self) -> list:
        if self.dry_run or not self._logged_in:
            return []
        try:
            from gmtrade.api import get_execution_reports
            return list(get_execution_reports(account=self.account_id) or [])
        except Exception:  # noqa: BLE001
            return []

    def get_positions(self) -> list:
        if self.dry_run or not self._logged_in:
            return []
        try:
            from gmtrade.api import get_positions
            return list(get_positions(account=self.account_id) or [])
        except Exception:  # noqa: BLE001
            return []

    def get_account(self) -> dict:
        if self.dry_run or not self._logged_in:
            return {"dry_run": True, "account": self.account_id,
                    "error": self.last_error or "未登录"}
        try:
            from gmtrade.api import get_cash
            c = get_cash(account=self.account_id)
            return {
                "available_cash": getattr(c, "available", None),
                "frozen_cash": getattr(c, "filled", None),
                "market_value": getattr(c, "market_value", None),
                "total_value": getattr(c, "nav", None),
                "account": self.account_id,
            }
        except Exception:  # noqa: BLE001
            return {"account": self.account_id, "error": "cash 查询失败"}

    def status(self) -> dict:
        return {
            "mode": "DRY_RUN" if self.dry_run else "LIVE",
            "channel": f"掘金仿真 (gmtrade @ {self.endpoint})",
            "account": self.account_id or "(未配置)",
            "token_registered": bool(self.token),
            "sdk_py_version": f"{sys.version_info.major}.{sys.version_info.minor}",
            "last_error": self.last_error or "",
        }
