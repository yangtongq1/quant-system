"""
QMT / miniQMT 仿真账户适配器（M5 执行层 · QMT 路线）

对接迅投 QMT（xtquant，官方 SDK，pip 可装）：
    from xtquant.xttrader import XtQuantTrader
    trader = XtQuantTrader(path, session_id)     # path = miniQMT userdata 路径
    trader.start()
    acc = trader.connect(account_id)             # account_id = QMT 资金账号

前置条件（用户侧）：
1. 券商开通 QMT/miniQMT 权限（国金/华西/方正/华宝等 10 万日均资产即可；软件免费）
2. Windows 上安装 QMT 客户端（券商提供下载），登录资金账号
3. miniQMT 模式：客户端内启动 miniQMT（极简模式），保持运行
4. .env 配置 QMT_ACCOUNT（资金账号）与 QMT_PATH（userdata_mini 路径，留空自动探测）

xtquant 未安装 / 客户端未运行 / 未配置账号：优雅降级 DryRun 模式
（订单只入本地库并标记 DRY_RUN，不发真实委托），策略代码可先行调试。

注意：sk-qmt 形式的密钥属于 QMT HTTP 网关生态（qmt-bridge 等），本适配器走
官方 xtquant SDK 直连，不需要密钥；密钥留作未来 HTTP 网关模式备用。
"""

from __future__ import annotations

import os
from datetime import datetime

from core.config import load_env
from execution.adapter import BrokerAdapter

load_env(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

# miniQMT userdata 常见安装路径（用于自动探测）
_QMT_PATH_CANDIDATES = [
    r"C:\QMT模拟交易端\userdata_mini",
    r"C:\华金QMT模拟交易\userdata_mini",
    r"C:\国金QMT交易端\userdata_mini",
    r"C:\bins_qmt\userdata_mini",
    r"C:\QMT\userdata_mini",
    r"D:\QMT\userdata_mini",
    r"C:\迅投极速交易终端\userdata_mini",
]


class QmtBroker(BrokerAdapter):
    """QMT / miniQMT 仿真账户执行器（xtquant 官方协议）。

    mode: "paper"（模拟盘，默认）/"live"（实盘，预留接口——实盘柜台路径与
    账号由 .env 的 QMT_LIVE_* 系列变量指定，未配置则拒绝启动防误发真单）。
    """

    def __init__(self, account: str | None = None, qmt_path: str | None = None,
                 dry_run_on_fail: bool = True, session_id: int | None = None,
                 mode: str = "paper"):
        self.mode = mode
        if mode == "live":
            # 实盘预留：路径/账号必须显式配置（QMT_LIVE_PATH/QMT_LIVE_ACCOUNT），
            # 未配置直接拒绝——防误连实盘柜台发真单
            live_path = os.environ.get("QMT_LIVE_PATH", "")
            live_acc = os.environ.get("QMT_LIVE_ACCOUNT", "")
            if not (live_path and live_acc):
                self._fail("实盘模式需配置 QMT_LIVE_PATH / QMT_LIVE_ACCOUNT（防误发真单，未配置拒绝启动）",
                           dry_run_on_fail)
                return
            account = account or live_acc
            qmt_path = qmt_path or live_path
        self.account = account or os.environ.get("QMT_ACCOUNT", "")
        self.api_key = os.environ.get("SUPERMIND_API_KEY", "")  # sk-qmt 密钥：登记，本通道不用
        self.qmt_path = qmt_path or os.environ.get("QMT_PATH", "")
        self.trader = None
        self.dry_run = False
        self.orders: list[dict] = []
        self.last_error: str = ""
        # 本地撮合核心（策略重放用，真实资金模拟；真实委托走 _order → QMT）
        # run_paper_signals 用它跑回测引擎拿目标持仓，差额调仓单再发 QMT
        from backtest.broker_sim import PaperBroker
        self.paper = PaperBroker(initial_cash=1_000_000.0)

        try:
            from xtquant.xttrader import XtQuantTrader  # noqa: F401
        except ImportError:
            self._fail("xtquant 未安装（pip install xtquant）", dry_run_on_fail)
            return

        if not self.account:
            self._fail("QMT_ACCOUNT 未配置（.env），无法连接仿真账户", dry_run_on_fail)
            return

        # 自动探测 userdata 路径
        if not self.qmt_path or not os.path.isdir(self.qmt_path):
            for p in _QMT_PATH_CANDIDATES:
                if os.path.isdir(p):
                    self.qmt_path = p
                    break
            else:
                if not self.qmt_path:
                    self._fail("QMT_PATH 未配置且未探测到 miniQMT userdata 目录"
                               "（需 QMT 客户端已安装并启动 miniQMT）", dry_run_on_fail)
                    return

        try:
            self._connect(session_id)
        except Exception as e:  # noqa: BLE001
            self._fail(f"QMT 连接失败: {type(e).__name__} {str(e)[:150]} "
                       f"（检查 miniQMT 是否启动、资金账号是否登录）", dry_run_on_fail)

    # ------------------------------------------------------------------
    def _fail(self, msg: str, dry_run_on_fail: bool):
        self.last_error = msg
        if dry_run_on_fail:
            self.dry_run = True
            print(f"[qmt] {msg} → 进入 DryRun 模式（订单仅本地记录，不发真实委托）")
        else:
            raise RuntimeError(msg)

    def _connect(self, session_id: int | None = None):
        """连接 miniQMT（客户端须已启动并登录）。

        含重试（session_id 撞号/瞬时握手失败时换 sid 重连，最多 3 次）。
        """
        import time as _time

        from xtquant.xttrader import XtQuantTrader
        from xtquant.xttype import StockAccount
        last_err: Exception | None = None
        for attempt in range(3):
            try:
                # session_id：同一进程内唯一即可；pid+时间戳派生，防撞号
                sid = session_id or (os.getpid() % 100000 * 1000
                                     + int(_time.time()) % 1000)
                self.trader = XtQuantTrader(self.qmt_path, sid)
                # 新版 xtquant（250807+）：start() 无返回值、connect() 无参、
                # 账号用 StockAccount 对象传入 subscribe()；旧版 connect(account_id)。
                started = self.trader.start()
                if started not in (None, 0):
                    raise RuntimeError(f"XtQuantTrader.start() 失败：{started}（miniQMT 未启动？）")
                import inspect
                n_params = len(inspect.signature(self.trader.connect).parameters)  # 含 self
                if n_params >= 2:
                    # 旧版 API：connect(account_id)
                    ok = self.trader.connect(self.account)
                else:
                    # 新版 API：connect() + subscribe(StockAccount)
                    ok = self.trader.connect()
                if ok not in (None, 0):
                    raise RuntimeError(f"connect() 失败：{ok}（miniQMT 未启动？）")
                break  # 连接成功
            except Exception as e:  # noqa: BLE001
                last_err = e
                session_id = None  # 重试换新 sid
                _time.sleep(1.5)
        else:
            raise last_err if last_err else RuntimeError("connect() 未知失败")
        self._account_obj = None
        # 订阅账号：东莞等券商柜台内部账号不带前导零（002038046455 → 2038046455）。
        # 两种形式都试，谁成功用谁。
        for acc_id in dict.fromkeys([self.account, self.account.lstrip("0")]):
            if not acc_id:
                continue
            try:
                cand = StockAccount(acc_id)
                if self.trader.subscribe(cand) == 0:
                    self._account_obj = cand
                    break
            except Exception:  # noqa: BLE001
                continue
        if self._account_obj is None:
            # 订阅失败不阻断（查询/下单仍可尝试；留错误给 status()）
            self._account_obj = StockAccount(self.account)
        self._XtQuantTrader = XtQuantTrader

    @property
    def account_id(self) -> str:
        """实际订阅成功的账号 ID（去前导零后的内部账号）。"""
        return getattr(self._account_obj, "account_id", self.account)

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
        from xtquant import xtconstant
        order_id = f"QM-{datetime.now().strftime('%Y%m%d%H%M%S%f')[:-3]}-{code}"
        if self.dry_run or self.trader is None:
            self.orders.append({"order_id": order_id, "code": code, "side": side,
                                "price": price, "volume": volume, "status": "DRY_RUN"})
            print(f"[qmt][DRY_RUN] {side} {code} {volume}@{price}")
            return order_id
        try:
            # 限价单：价格必须是合法 tick（A 股股票/ETF 0.01 元），三位小数必被柜台拒绝
            if price and price > 0:
                ptype = xtconstant.FIX_PRICE
                px = round(float(price), 2)
            else:
                # 市价单：最新价转对手价（ETF/股票市价类型，5=最新价）
                ptype = xtconstant.LATEST_PRICE
                px = -1
            rtype = xtconstant.STOCK_BUY if side == "buy" else xtconstant.STOCK_SELL
            oid = self.trader.order_stock(
                account=self._account_obj, stock_code=self._symbol(code),
                order_type=rtype, order_volume=int(volume),
                price_type=ptype, price=px,
                strategy_name="cross_asset", order_remark="quant-system",
            )
            # 返回值：<0 为失败（-1 连接断开/参数非法），>0 为柜台委托号
            if oid is None or (isinstance(oid, int) and oid < 0):
                self.orders.append({"order_id": order_id, "code": code, "side": side,
                                    "price": px, "volume": volume, "status": "REJECTED",
                                    "reason": f"order_stock 返回 {oid}（连接断开/参数非法）"})
                print(f"[qmt] 下单失败 {side} {code} {volume}@{px}: order_stock={oid}")
                return order_id
            self.orders.append({"order_id": order_id, "code": code, "side": side,
                                "price": px, "volume": volume,
                                "status": "SUBMITTED", "xt_id": oid})
            print(f"[qmt] 已委托 {side} {code} {volume}@{px} → 柜台号 {oid}")
            return order_id
        except Exception as e:  # noqa: BLE001
            self.orders.append({"order_id": order_id, "code": code, "side": side,
                                "price": price, "volume": volume, "status": "REJECTED",
                                "reason": str(e)[:120]})
            return order_id

    def cancel(self, order_id: str) -> bool:
        if self.dry_run or self.trader is None:
            return False
        try:
            return bool(self.trader.cancel_order_stock(self._account_obj, int(order_id)))
        except Exception:  # noqa: BLE001
            return False

    def get_orders(self) -> list:
        if self.dry_run or self.trader is None:
            return []
        try:
            return list(self.trader.query_stock_orders(self._account_obj) or [])
        except Exception:  # noqa: BLE001
            return []

    def get_trades(self) -> list:
        if self.dry_run or self.trader is None:
            return []
        try:
            return list(self.trader.query_stock_trades(self._account_obj) or [])
        except Exception:  # noqa: BLE001
            return []

    def get_positions(self) -> list:
        if self.dry_run or self.trader is None:
            return []
        try:
            return list(self.trader.query_stock_positions(self._account_obj) or [])
        except Exception:  # noqa: BLE001
            return []

    def get_account(self) -> dict:
        if self.dry_run or self.trader is None:
            return {"dry_run": True, "account": self.account,
                    "error": self.last_error or "未连接"}
        try:
            a = self.trader.query_stock_asset(self._account_obj)
            if a is None:
                return {"account": self.account_id, "error": "查询失败"}
            return {
                "available_cash": getattr(a, "cash", None),
                "market_value": getattr(a, "market_value", None),
                "frozen_cash": getattr(a, "frozen_cash", None),
                "total_value": getattr(a, "total_asset", None),
                "account": self.account_id,
            }
        except Exception:  # noqa: BLE001
            return {"account": self.account_id, "error": "asset 查询失败"}

    def status(self) -> dict:
        """连接状态一览（控制台/诊断用）。"""
        return {
            "mode": "DRY_RUN" if self.dry_run else "LIVE",
            "channel": "QMT/miniQMT (xtquant)",
            "account": self.account or "(未配置)",
            "qmt_path": self.qmt_path or "(未探测到)",
            "api_key_registered": bool(self.api_key),
            "last_error": self.last_error or "",
        }
