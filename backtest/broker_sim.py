"""
撮合模拟模块（难点模块之二）

职责：模拟订单撮合，正确处理 T+1、涨跌停、停牌、交易成本、滑点。

红线（智谱接续开发务必遵守）：
1. T+1：当日买入的股票当日不可卖出。
2. 执行时点：默认「次日开盘成交」（信号 T 日收盘后产生，T+1 开盘成交），杜绝未来函数。
3. 涨跌停：一字涨停买不进、一字跌停卖不出；停牌不可成交。
4. 成本必须计入：佣金 + 印花税 + 过户费 + 滑点。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Position:
    """持仓。available 为可卖数量（受 T+1 限制）。"""
    code: str
    volume: int = 0
    available: int = 0
    avg_cost: float = 0.0  # 摊入费用后的平均成本


def compute_limit_prices(prev_close: float, limit_rate: float = 0.10):
    """由昨收价计算涨停价/跌停价（四舍五入到分）。"""
    limit_up = round(prev_close * (1 + limit_rate), 2)
    limit_down = round(prev_close * (1 - limit_rate), 2)
    return limit_up, limit_down


def can_buy_on_open(bar: dict, limit_rate: float = 0.10) -> bool:
    """次日开盘能否买入。不能：停牌 / 开盘即触及涨停（一字板）。"""
    if not bar.get("is_trading", 1):
        return False
    prev_close = bar.get("prev_close")
    if prev_close and prev_close > 0:
        limit_up, _ = compute_limit_prices(prev_close, limit_rate)
        if bar["open"] >= limit_up - 1e-6:
            return False
    return True


def can_sell_on_open(bar: dict, limit_rate: float = 0.10) -> bool:
    """次日开盘能否卖出。不能：停牌 / 开盘即触及跌停（一字板）。"""
    if not bar.get("is_trading", 1):
        return False
    prev_close = bar.get("prev_close")
    if prev_close and prev_close > 0:
        _, limit_down = compute_limit_prices(prev_close, limit_rate)
        if bar["open"] <= limit_down + 1e-6:
            return False
    return True


class PaperBroker:
    """模拟资金账户 + 撮合。费率可配，默认 A 股常规水平。"""

    def __init__(
        self,
        initial_cash: float = 1_000_000.0,
        commission_rate: float = 2.5e-4,   # 佣金 万 2.5
        min_commission: float = 5.0,       # 最低佣金 5 元
        stamp_tax_rate: float = 5e-4,      # 印花税 0.05%（仅卖出）
        transfer_fee_rate: float = 1e-5,   # 过户费 0.001%（双边）
        slippage: float = 0.0,             # 滑点比例，买入加价/卖出减价
    ):
        self.initial_cash = initial_cash
        self.cash = initial_cash
        self.commission_rate = commission_rate
        self.min_commission = min_commission
        self.stamp_tax_rate = stamp_tax_rate
        self.transfer_fee_rate = transfer_fee_rate
        self.slippage = slippage

        self.positions: dict[str, Position] = {}
        self._today_bought: dict[str, int] = {}  # 今日买入（T+1 锁定，次日解锁）
        self.trades: list[dict] = []             # 成交流水
        self.current_date: str | None = None     # 由引擎注入当前交易日（成交流水用）

    # ---------- 成本 ----------
    def _commission(self, amount: float) -> float:
        return max(amount * self.commission_rate, self.min_commission)

    def _stamp_tax(self, amount: float) -> float:
        return amount * self.stamp_tax_rate

    def _transfer_fee(self, amount: float) -> float:
        return amount * self.transfer_fee_rate

    def _buy_cost(self, amount: float) -> float:
        return self._commission(amount) + self._transfer_fee(amount)

    def _sell_cost(self, amount: float) -> float:
        return self._commission(amount) + self._stamp_tax(amount) + self._transfer_fee(amount)

    # ---------- 下单 ----------
    def buy(self, code: str, price: float, volume: int):
        """买入。price 为参考价，实际成交价应用滑点。资金不足返回 None。"""
        if volume <= 0 or price <= 0:
            return None
        fill_price = price * (1 + self.slippage)
        amount = fill_price * volume
        fee = self._buy_cost(amount)
        total = amount + fee
        if total > self.cash + 1e-6:
            return None

        self.cash -= total
        pos = self.positions.setdefault(code, Position(code=code))
        new_volume = pos.volume + volume
        pos.avg_cost = (pos.avg_cost * pos.volume + total) / new_volume
        pos.volume = new_volume
        self._today_bought[code] = self._today_bought.get(code, 0) + volume

        self.trades.append({
            "code": code, "side": "buy", "price": round(fill_price, 4),
            "volume": volume, "fee": round(fee, 4),
            "date": self.current_date or "",
        })
        return fill_price

    def sell(self, code: str, price: float, volume: int):
        """卖出。price 为参考价，实际成交价应用滑点。超过可卖数量返回 None。"""
        pos = self.positions.get(code)
        if pos is None or volume <= 0 or price <= 0:
            return None
        if volume > pos.available:
            return None  # 超过 T+1 可卖数量

        fill_price = price * (1 - self.slippage)
        amount = fill_price * volume
        fee = self._sell_cost(amount)
        self.cash += amount - fee

        pos.volume -= volume
        pos.available -= volume
        if pos.volume <= 0:
            del self.positions[code]

        self.trades.append({
            "code": code, "side": "sell", "price": round(fill_price, 4),
            "volume": volume, "fee": round(fee, 4),
            "date": self.current_date or "",
        })
        return fill_price

    # ---------- 结算 ----------
    def next_day(self):
        """每日收盘结算：今日买入解锁为可卖（T+1）。"""
        for code, vol in self._today_bought.items():
            pos = self.positions.get(code)
            if pos is not None:
                pos.available += vol
        self._today_bought = {}

    # ---------- 查询 ----------
    def market_value(self, price_map: dict[str, float]) -> float:
        total = 0.0
        for code, pos in self.positions.items():
            px = price_map.get(code, pos.avg_cost)
            total += px * pos.volume
        return total

    def total_asset(self, price_map: dict[str, float]) -> float:
        return self.cash + self.market_value(price_map)
