"""
事件驱动回测引擎（M2 核心）

红线（必守）：
1. 无未来函数：T 日产生的信号只能用截至 T 日数据，T+1 开盘成交。
2. 回测/模拟盘共用策略代码：同一 Strategy 类，仅 Broker 不同。
3. T+1 / 涨跌停 / 停牌 由撮合层强制执行，策略无法绕过。

循环结构（每个交易日）：
  before_trading → 处理昨日信号（T+1 开盘成交）→ on_bar → after_trading → 结算
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from backtest.broker_sim import PaperBroker, can_buy_on_open, can_sell_on_open
from backtest.metrics import compute_metrics
from strategy.base import Context


@dataclass
class BacktestResult:
    """回测结果。"""
    equity: pd.Series                 # 净值序列（日期索引）
    trades: list                       # 成交流水
    metrics: dict                      # 绩效指标
    daily_positions: list = field(default_factory=list)  # 每日持仓快照


class BacktestEngine:
    """事件驱动回测引擎（逐交易日循环）。"""

    def __init__(
        self,
        strategy,
        broker: PaperBroker | None = None,
        initial_cash: float = 1_000_000.0,
    ):
        self.strategy = strategy
        self.broker = broker or PaperBroker(initial_cash=initial_cash)
        self.initial_cash = initial_cash

    def run(self, bars: dict[str, pd.DataFrame]) -> BacktestResult:
        """执行回测。

        参数
        ----
        bars : {code: 标准日线 DataFrame}，须含 date/open/high/low/close/volume/adj_factor
               （复权口径由调用方决定，引擎不隐式复权）
        """
        if not bars:
            raise ValueError("bars 为空")

        # 统一交易日轴：所有标的日期并集（按日历升序）
        all_dates = sorted(set().union(*[
            set(pd.to_datetime(df["date"]).dt.normalize()) for df in bars.values()
        ]))

        # 按日期建索引：date -> {code: bar_dict}
        # 性能：用 itertuples + 预转 dict 代替 iterrows（360 只 × 1700 日 < 10 秒）
        bars_by_date: dict[pd.Timestamp, dict[str, dict]] = {d: {} for d in all_dates}
        for code, df in bars.items():
            df = df.copy()
            df["date"] = pd.to_datetime(df["date"]).dt.normalize()
            df = df.sort_values("date").drop_duplicates(subset="date", keep="last")
            records = df.to_dict("records")  # 整表一次性转 dict 列表（C 级速度）
            for rec in records:
                rec["code"] = code
                bars_by_date[rec["date"]][code] = rec

        ctx = Context(broker=self.broker, defer_execution=True)
        self.strategy.init(ctx)

        # 待执行信号队列：{(code, side): (price, volume)}，T 日收盘生成，T+1 开盘成交
        pending_orders: list[dict] = []

        equity_dates: list = []
        equity_values: list = []

        for d in all_dates:
            today_bars = bars_by_date[d]

            # 1. 盘前（注入当前日期，策略可用于交易日轴推进）
            ctx.current_date = d
            ctx.portfolio = self._portfolio_snapshot(today_bars)
            self.strategy.before_trading(ctx)

            # 2. T+1 开盘成交：处理昨日收盘后生成的信号
            for order in pending_orders:
                self._fill_order(order, today_bars)
            pending_orders = []

            # 3. 盘中：策略逐标的观察，生成信号（下一交易日成交）
            for code, bar in today_bars.items():
                self.strategy.on_bar(ctx, bar)

            # 4. 收集策略在 on_bar 中生成的信号（延迟到 T+1）
            pending_orders = ctx.pop_pending_orders()

            # 5. 盘后
            self.strategy.after_trading(ctx)

            # 6. 结算：T+1 解锁、记录净值
            self.broker.next_day()
            price_map = {c: b.get("close", 0.0) for c, b in today_bars.items()}
            equity_dates.append(d)
            equity_values.append(self.broker.total_asset(price_map))

        equity = pd.Series(equity_values, index=pd.DatetimeIndex(equity_dates), name="equity")
        metrics = compute_metrics(equity)
        return BacktestResult(equity=equity, trades=self.broker.trades, metrics=metrics)

    # ------------------------------------------------------------------
    def _portfolio_snapshot(self, today_bars: dict[str, dict]) -> dict:
        """账户快照：现金 / 持仓 / 总资产（按当日 close 估值）。"""
        price_map = {c: b.get("close", 0.0) for c, b in today_bars.items()}
        positions = {
            code: {"volume": pos.volume, "available": pos.available,
                   "avg_cost": pos.avg_cost,
                   "market_value": price_map.get(code, pos.avg_cost) * pos.volume}
            for code, pos in self.broker.positions.items()
        }
        return {
            "cash": self.broker.cash,
            "positions": positions,
            "total_asset": self.broker.total_asset(price_map),
        }

    def _fill_order(self, order: dict, today_bars: dict[str, dict]):
        """T+1 开盘价撮合，执行涨跌停/停牌/T+1 校验。"""
        code = order["code"]
        bar = today_bars.get(code)
        if bar is None:
            return  # 当日无行情（退市/长期停牌），跳过
        if not bar.get("is_trading", 1):
            return  # 停牌
        if order["side"] == "buy" and not can_buy_on_open(bar, order.get("limit_rate", 0.10)):
            return
        if order["side"] == "sell" and not can_sell_on_open(bar, order.get("limit_rate", 0.10)):
            return
        open_price = float(bar["open"])
        if order["side"] == "buy":
            self.broker.buy(code, open_price, order["volume"])
        else:
            self.broker.sell(code, open_price, order["volume"])
