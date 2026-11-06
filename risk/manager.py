"""
风控规则库（M6）

三层风控：
- 事前：单标的持仓上限 / 单笔仓位上限 / 资金额度校验（下单前强制校验，不过直接拒绝）
- 事中：实时敞口监控 / 异常订单拦截（价格偏离 / 频率）
- 事后：当日盈亏 / 回撤复盘 / 风控事件留痕

风控独立于策略，在 BrokerAdapter 之前强制执行（红线 10）。
"""

from __future__ import annotations

import numpy as np
import pandas as pd


class RiskRules:
    """可配置风控规则集（阈值从 config.yaml 加载）。"""

    def __init__(
        self,
        max_position_pct: float = 0.20,     # 单标的市值占总资产上限
        max_order_pct: float = 0.05,        # 单笔订单金额占总资产上限
        max_drawdown: float = 0.20,        # 组合最大回撤硬约束
        max_single_stock_pct: float = 0.02, # 单只个股权重上限（选股策略）
        price_deviation: float = 0.10,     # 限价偏离参考价上限（异常单拦截）
        max_orders_per_day: int = 50,      # 单日订单数上限（频率拦截）
    ):
        self.max_position_pct = max_position_pct
        self.max_order_pct = max_order_pct
        self.max_drawdown = max_drawdown
        self.max_single_stock_pct = max_single_stock_pct
        self.price_deviation = price_deviation
        self.max_orders_per_day = max_orders_per_day

    # ---------- 事前 ----------
    def check_pre_trade(self, portfolio: dict, code: str, side: str,
                        price: float, volume: int, ref_price: float | None = None) -> tuple[bool, str]:
        """事前校验：不过直接拒绝下单。"""
        total = portfolio.get("total_asset", 0.0)
        cash = portfolio.get("cash", 0.0)
        if total <= 0:
            return False, "总资产非正，拒绝交易"

        order_value = price * volume
        if order_value <= 0:
            return False, "订单金额非正"

        # 1. 单笔金额上限
        if order_value > total * self.max_order_pct:
            return False, f"单笔金额 {order_value:.0f} 超上限 {self.max_order_pct:.0%} 总资产"

        # 2. 资金校验（买入）
        if side == "buy" and order_value > cash:
            return False, f"可用资金 {cash:.0f} 不足（订单需 {order_value:.0f}）"

        # 3. 单标的持仓上限（买入后市值）
        positions = portfolio.get("positions", {})
        pos = positions.get(code, {})
        cur_value = pos.get("volume", 0) * price
        if side == "buy":
            after = cur_value + order_value
            if after > total * self.max_position_pct:
                return False, f"{code} 买入后市值占比 {after / total:.1%} 超上限 {self.max_position_pct:.0%}"

        # 4. 价格偏离（异常单拦截，防乌龙指）
        if ref_price is not None and ref_price > 0:
            dev = abs(price - ref_price) / ref_price
            if dev > self.price_deviation:
                return False, f"价格偏离 {dev:.1%} 超上限 {self.price_deviation:.0%}（疑似异常单）"

        return True, ""

    # ---------- 事中 ----------
    def check_intraday(self, portfolio: dict, prices: dict[str, float]) -> list[str]:
        """事中敞口监控：返回告警列表（不拦截，触发阈值建议减仓）。"""
        alerts = []
        total = portfolio.get("total_asset", 0.0)
        if total <= 0:
            return alerts
        positions = portfolio.get("positions", {})
        for code, pos in positions.items():
            px = prices.get(code, pos.get("avg_cost", 0.0))
            value = pos.get("volume", 0) * px
            pct = value / total
            if pct > self.max_position_pct:
                alerts.append(f"{code} 敞口 {pct:.1%} 超上限 {self.max_position_pct:.0%}，建议减仓")
        return alerts

    # ---------- 事后 ----------
    def check_post(self, equity: pd.Series) -> list[str]:
        """事后回撤复盘。"""
        alerts = []
        if len(equity) < 2:
            return alerts
        equity = pd.Series(equity, dtype=float)
        peak = equity.cummax()
        dd = equity / peak - 1.0
        mdd = float(dd.min())
        if mdd < -self.max_drawdown:
            alerts.append(f"组合回撤 {mdd:.1%} 已破硬约束 {self.max_drawdown:.0%}")
        return alerts


class RiskManager:
    """风控管理器：独立于策略，强制执行（事件留痕）。"""

    def __init__(self, rules: RiskRules | None = None):
        self.rules = rules or RiskRules()
        self.events: list[dict] = []       # 风控事件留痕（append-only）
        self._order_count_today = 0
        self._today = None

    def pre_trade_check(self, portfolio: dict, code: str, side: str,
                        price: float, volume: int, ref_price: float | None = None) -> tuple[bool, str]:
        """事前校验入口（BrokerAdapter 调用）。"""
        ok, reason = self.rules.check_pre_trade(portfolio, code, side, price, volume, ref_price)
        if not ok:
            self._log_event("pre_trade_reject", code, side, price, volume, reason)
        return ok, reason

    def check_frequency(self, today: str) -> tuple[bool, str]:
        """单日订单频率校验。"""
        if self._today != today:
            self._today = today
            self._order_count_today = 0
        self._order_count_today += 1
        if self._order_count_today > self.rules.max_orders_per_day:
            reason = f"单日订单数 {self._order_count_today} 超上限 {self.rules.max_orders_per_day}"
            self._log_event("frequency_reject", "", "", 0.0, 0, reason)
            return False, reason
        return True, ""

    def intraday_check(self, portfolio: dict, prices: dict[str, float]) -> list[str]:
        """事中监控入口。"""
        alerts = self.rules.check_intraday(portfolio, prices)
        for a in alerts:
            self._log_event("intraday_alert", "", "", 0.0, 0, a)
        return alerts

    def post_check(self, equity: pd.Series) -> list[str]:
        """事后复盘入口。"""
        alerts = self.rules.check_post(equity)
        for a in alerts:
            self._log_event("post_alert", "", "", 0.0, 0, a)
        return alerts

    def _log_event(self, etype: str, code: str, side: str, price: float,
                   volume: int, detail: str):
        """事件溯源：append-only 留痕。"""
        import datetime
        self.events.append({
            "time": datetime.datetime.now().isoformat(timespec="seconds"),
            "type": etype, "code": code, "side": side,
            "price": price, "volume": volume, "detail": detail,
        })
