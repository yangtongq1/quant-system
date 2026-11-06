"""
示例策略：双均线（最小可运行样例，验证全链路贯通）

- 短均线上穿长均线 → 买入；短均线下穿长均线 → 卖出
- 信号 T 日收盘后产生，T+1 开盘成交（引擎保证，杜绝未来函数）
"""

from __future__ import annotations

import pandas as pd

from strategy.base import Context, Strategy


class DualMAStrategy(Strategy):
    """双均线策略。params: fast=5, slow=20。"""

    def __init__(self, fast: int = 5, slow: int = 20):
        assert fast < slow, "fast 必须小于 slow"
        self.fast = fast
        self.slow = slow
        self._hist: dict[str, pd.DataFrame] = {}

    def init(self, context: Context):
        self._hist = {}

    def on_bar(self, context: Context, bar: dict):
        code = bar["code"]
        price = float(bar["close"])

        # 累积历史（只用截至当日的数据）
        if code not in self._hist:
            self._hist[code] = pd.DataFrame(columns=["close"])
        self._hist[code].loc[bar["date"]] = price

        closes = self._hist[code]["close"]
        if len(closes) < self.slow:
            return

        ma_fast = closes.rolling(self.fast).mean().iloc[-1]
        ma_slow = closes.rolling(self.slow).mean().iloc[-1]

        holding = context.portfolio["positions"].get(code) if context.portfolio else None
        # 量：按 10 万名义值取整百（A 股一手 100 股）
        volume = max(int(100_000 / price / 100) * 100, 100)

        if ma_fast > ma_slow and holding is None:
            context.buy(code, price, volume)
        elif ma_fast < ma_slow and holding is not None:
            context.sell(code, price, holding["volume"])
