"""多策略体系（对冲 + 非对冲）

用户诉求：单一 λ 并轨策略不一定适应 A 股风格切换，需要多策略横向对比，
对冲/非对冲都要有，能跑回测对比。

策略清单：
════════════════════════════════════════════════════════════════════
【对冲类】股票+黄金+纳指三资产，对照 λ 并轨机制的每个成分
════════════════════════════════════════════════════════════════════
1. EqualWeightStrategy（等权再平衡，对冲基准）
   三资产固定 1/3:1/3:1/3，月末再平衡，无任何择时。
   对照问题：λ 并轨相对「无脑等权」是否真有增量？

2. RiskParityStrategy（纯风险平价，对冲）
   权重 ∝ 1/σ（60 日年化波动率），月末再平衡，无固定基准。
   对照问题：动态择时成分（风险平价）单独拿出来是否成立？
   （与 CrossAsset 的 λ→1 极限形式等价，但无动量调整、无 [10%,70%] 裁剪）

【非对冲类】单一资产暴露，对照对冲贡献
════════════════════════════════════════════════════════════════════
3. StockOnlyStrategy（多因子纯股票，非对冲）
   复用 CrossAssetStrategy 的多因子选股，100% 股票仓。
   对照问题：黄金/纳指对冲贡献了什么？（收益/回撤/夏普差分）

4. ETFMomentumStrategy（ETF 动量轮动，非对冲）
   518880/513100/510300 三只 ETF，60 日动量前 2 名等权，月末换仓。
   对照问题：简单 ETF 轮动 vs 多因子选股+对冲的差距。

架构说明：
- 前三个策略继承 CrossAssetStrategy，复用全部基建（选股/调仓/限流/
  交易日轴/增量缓存），仅覆写 target_weights/dynamic_weights——
  「同框架横向对比」的关键：差异只来自策略逻辑，不来自实现差异。
- ETFMomentumStrategy 独立实现（标的池不同，无需股票端基建）。

红线：所有信号只用截至 T 日收盘数据，成交在 T+1 开盘（引擎保证）。
"""

from __future__ import annotations

import bisect

import numpy as np
import pandas as pd

from strategy.base import Context, Strategy
from strategy.cross_asset import CrossAssetStrategy


# ══════════════════════════════════════════════════════════════════
# 对冲类 1：等权再平衡（基准对照）
# ══════════════════════════════════════════════════════════════════
class EqualWeightStrategy(CrossAssetStrategy):
    """三资产等权再平衡（对冲基准）。

    固定 1/3:1/3:1/3，月末再平衡，无择时。
    股票端用与 CrossAsset 相同的多因子选股（保证唯一差异是资产配置层）。
    """

    def __init__(self, *args, **kwargs):
        if "base_weights" not in kwargs:
            kwargs["base_weights"] = {"stock": 1 / 3, "gold": 1 / 3, "nasdaq": 1 / 3}
        if "rebalance_freq" not in kwargs:
            kwargs["rebalance_freq"] = "monthly"
        kwargs["lam"] = 0.0
        super().__init__(*args, **kwargs)
        # 等权 = 纯基准：λ 强制归零（最终权重 = 固定基准权重）
        self.lam = 0.0

    def target_weights(self) -> dict:
        return {"stock": 1 / 3, "gold": 1 / 3, "nasdaq": 1 / 3}

    def dynamic_weights(self) -> dict:
        """无择时：返回等权。"""
        return {"stock": 1 / 3, "gold": 1 / 3, "nasdaq": 1 / 3}


# ══════════════════════════════════════════════════════════════════
# 对冲类 2：纯风险平价
# ══════════════════════════════════════════════════════════════════
class RiskParityStrategy(CrossAssetStrategy):
    """纯风险平价（对冲）：权重 ∝ 1/σ，无固定基准。

    σ_i = 过去 60 日收益标准差 × √252（年化）
    w_i = (1/σ_i) / Σ(1/σ_j)

    与 CrossAsset λ→1 极限的差别：
    - 无动量调整（纯波动率平价）
    - 无 [10%, 70%] 裁剪（风险平价可给出极端权重）
    - 无固定基准并轨（100% 动态）
    """

    def __init__(self, *args, **kwargs):
        if "rebalance_freq" not in kwargs:
            kwargs["rebalance_freq"] = "monthly"
        kwargs["lam"] = 1.0
        super().__init__(*args, **kwargs)
        self.lam = 1.0

    def target_weights(self) -> dict:
        """纯风险平价：直接返回 1/σ 权重。"""
        return self.dynamic_weights()

    def dynamic_weights(self) -> dict:
        """1/σ 风险平价（无动量调整、无裁剪）。"""
        rets = {}
        for k, s in (("stock", self._stock_index_series()),
                     ("gold", self._gold_close.to_series() if self._gold_close is not None else None),
                     ("nasdaq", self._nasdaq_close.to_series() if self._nasdaq_close is not None else None)):
            if s is None or len(s) < self.lookback:
                return dict(self.base_weights)  # 数据不足，退回基准
            rets[k] = s.pct_change().dropna().iloc[-self.lookback:]

        sigmas = {k: float(r.std()) * np.sqrt(252) for k, r in rets.items()}
        inv_vol = {k: (1.0 / v if v > 0 else 0.0) for k, v in sigmas.items()}
        total = sum(inv_vol.values())
        if total <= 0:
            return dict(self.base_weights)
        return {k: v / total for k, v in inv_vol.items()}


# ══════════════════════════════════════════════════════════════════
# 非对冲类 1：多因子纯股票
# ══════════════════════════════════════════════════════════════════
class StockOnlyStrategy(CrossAssetStrategy):
    """多因子纯股票策略（非对冲）：100% 股票仓，无对冲资产。

    复用 CrossAsset 的多因子选股（动量/波动率/反转/基本面），
    权重层强制 stock=1.0、gold=nasdaq=0。
    """

    def __init__(self, *args, **kwargs):
        kwargs["base_weights"] = {"stock": 1.0, "gold": 0.0, "nasdaq": 0.0}
        kwargs["lam"] = 0.0
        if "rebalance_freq" not in kwargs:
            kwargs["rebalance_freq"] = "monthly"
        super().__init__(*args, **kwargs)
        self.lam = 0.0
        self.base_weights = {"stock": 1.0, "gold": 0.0, "nasdaq": 0.0}

    def target_weights(self) -> dict:
        return {"stock": 1.0, "gold": 0.0, "nasdaq": 0.0}

    def dynamic_weights(self) -> dict:
        return {"stock": 1.0, "gold": 0.0, "nasdaq": 0.0}


# ══════════════════════════════════════════════════════════════════
# 非对冲类 2：ETF 动量轮动
# ══════════════════════════════════════════════════════════════════
class ETFMomentumStrategy(Strategy):
    """ETF 动量轮动（非对冲）：三只 ETF 60 日动量前 2 名等权。

    标的池：518880 黄金 / 513100 纳指 / 510300 沪深300
    规则：月末计算 60 日动量，持有动量最高的前 2 名（须动量>0），各 50%。
    全部为负动量时持有动量最高的一只（弱势避险，不空仓——防踏空反弹）。
    """

    def __init__(
        self,
        etf_codes: list[str] | None = None,
        hold_top: int = 2,
        momentum_window: int = 60,
        rebalance_band: float = 0.10,
    ):
        self.etf_codes = etf_codes or ["518880", "513100", "510300"]
        self.hold_top = hold_top
        self.momentum_window = momentum_window
        self.rebalance_band = rebalance_band
        # 运行时状态
        self._closes: dict[str, list[float]] = {}
        self._dates: dict[str, list] = {}
        self._global_dates: list = []
        self._last_rebalance_month: tuple | None = None
        self._last_check_date: pd.Timestamp | None = None

    def init(self, context: Context):
        self._closes = {c: [] for c in self.etf_codes}
        self._dates = {c: [] for c in self.etf_codes}
        self._global_dates = []
        self._last_rebalance_month = None
        self._last_check_date = None

    def on_bar(self, context: Context, bar: dict):
        code = bar["code"]
        if code not in self.etf_codes:
            return
        # 后复权口径（防 ETF 分红除权跳空）
        adj = float(bar.get("adj_factor", 1.0) or 1.0)
        close = float(bar["close"]) * adj
        date = pd.to_datetime(bar["date"])
        self._closes[code].append(close)
        self._dates[code].append(date)
        # 全局交易日轴推进（每日期只记一次）
        if not self._global_dates or self._global_dates[-1] != date:
            self._global_dates.append(date)
        self._maybe_rebalance(context, date)

    def _maybe_rebalance(self, context: Context, date: pd.Timestamp):
        """每月首个判定日触发（沿主策略口径：_last_rebalance_month 防重）。

        注：与 CrossAsset 月频模式一致——逐日推进的交易日轴上，
        每月第一个满足窗口条件的日期触发一次，防重靠月份去重。
        红线：只用截至 T 日数据，T+1 开盘成交（引擎保证）。
        """
        if any(len(self._closes[c]) < self.momentum_window + 1 for c in self.etf_codes):
            return
        if self._last_check_date == date:
            return
        self._last_check_date = date

        if not self._is_month_last_trading_day(date):
            return
        month = (date.year, date.month)
        if self._last_rebalance_month == month:
            return
        self._last_rebalance_month = month
        self._rebalance(context, date)

    def _is_month_last_trading_day(self, date) -> bool:
        """全局交易日轴上月末判定（与 CrossAsset 相同口径）。"""
        axis = self._global_dates
        if not axis:
            return False
        if axis[-1] == date:
            return True  # 数据末尾视为月末
        i = bisect.bisect_left(axis, date)
        if i >= len(axis) or axis[i] != date:
            return False
        if i + 1 < len(axis):
            return axis[i + 1].month != date.month
        return True

    def _rebalance(self, context: Context, date: pd.Timestamp):
        """动量排序 → 前 2 名等权 → 差额调仓。"""
        total = context.portfolio["total_asset"]
        if total <= 0:
            return
        moms: dict[str, float] = {}
        for c in self.etf_codes:
            vals = self._closes[c]
            if len(vals) < self.momentum_window + 1:
                continue
            first = vals[-self.momentum_window - 1]
            last = vals[-1]
            if first > 0:
                moms[c] = last / first - 1.0
        if not moms:
            return
        ranked = sorted(moms.items(), key=lambda kv: kv[1], reverse=True)
        hold = [c for c, m in ranked[:self.hold_top] if m > 0]
        if not hold:
            hold = [ranked[0][0]]  # 全负动量 → 持动量最高一只（防踏空）
        # 买入预算打 98 折：预留佣金/过户费/次日开盘跳空缓冲，
        # 防 100% 满仓买入因费用差一点点被整单拒绝（资金不足拒单）
        per = total * 0.98 / len(hold)

        for c in self.etf_codes:
            target = per if c in hold else 0.0
            self._adjust(context, c, target)

    def _adjust(self, context: Context, code: str, target_value: float):
        """差额调仓（100 股整数，band=10% 控换手）。"""
        pos = context.portfolio["positions"].get(code)
        cur = pos["market_value"] if pos else 0.0
        diff = target_value - cur
        if abs(diff) < self.rebalance_band * max(target_value, cur, 1.0):
            return
        price = self._last_price(code)
        if not price or price <= 0:
            return
        lots = int(abs(diff) / price / 100) * 100
        if lots <= 0:
            return
        if diff > 0:
            context.buy(code, price, lots)
        else:
            vol = min(lots, pos["volume"] if pos else 0)
            if vol > 0:
                context.sell(code, price, vol)

    def _last_price(self, code: str) -> float | None:
        vals = self._closes.get(code)
        if not vals:
            return None
        return float(vals[-1])
