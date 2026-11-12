"""
核心策略：跨资产对冲配置（日频，不做期货）

三资产端：
1. A 股多因子选股（Alpha 端）：多因子打分 → 截面排序 → top N 等权
2. 黄金 ETF 518880（避险/分散端）
3. 纳指 ETF 513100（全球化分散端，非对冲）

配置引擎：固定基准权重与动态择时「并轨」——
    最终权重 = 固定基准权重 × (1 − λ) + 动态择时权重 × λ
- λ=0.1 稳健 / 0.5 平衡 / 0.9 进取，底层数据/因子/信号完全复用
- 动态择时权重 = 风险平价（1/σ）+ 动量调整，裁剪到 [10%, 70%]

再平衡：每月最后一个交易日检查，任一资产权重偏离 >5% 触发，
只调整超出阈值的部分（控制换手成本）。

红线：所有信号只用截至 T 日收盘数据，成交在 T+1 开盘（引擎保证）。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from factors.neutralize import zscore
from strategy.base import Context, Strategy


class CrossAssetStrategy(Strategy):
    """跨资产对冲配置策略。

    params:
        gold_code: 黄金 ETF 代码（默认 518880）
        nasdaq_code: 纳指 ETF 代码（默认 513100）
        base_weights: 固定基准权重 dict（默认 6:2:2）
        lam: 风险档位 λ（0.1 稳健 / 0.5 平衡 / 0.9 进取）
        top_n: 股票池持股数（默认 50）
        rebalance_band: 再平衡触发阈值（默认 0.05）
        lookback: 动态择时回看窗口（默认 60 日）
        momentum_window: 动量窗口（默认 60 日）
    """

    def __init__(
        self,
        gold_code: str = "518880",
        nasdaq_code: str = "513100",
        base_weights: dict | None = None,
        lam: float = 0.5,
        top_n: int = 50,
        rebalance_band: float = 0.05,
        lookback: int = 60,
        momentum_window: int = 60,
        stock_codes: list[str] | None = None,
        fundamentals: pd.DataFrame | None = None,
        allow_chinext: bool = True,
        allow_star: bool = True,
        main_board_only: bool = False,
        exclude_st: bool = True,
        stock_meta: pd.DataFrame | None = None,
        rebalance_freq: str = "monthly",
        select_refresh_days: int = 5,
        max_buy_2d_pct: float = 0.0,
    ):
        self.gold_code = gold_code
        self.nasdaq_code = nasdaq_code
        self.base_weights = base_weights or {"stock": 0.6, "gold": 0.2, "nasdaq": 0.2}
        self.lam = lam
        self.top_n = top_n
        self.rebalance_band = rebalance_band
        self.lookback = lookback
        self.momentum_window = momentum_window
        self.stock_codes = stock_codes or []
        # 市场权限过滤（模拟账户未开通创业板/科创板权限时剔除，防废单）
        self.allow_chinext = allow_chinext   # 创业板 300/301
        self.allow_star = allow_star         # 科创板 688
        # 稳健过滤：仅主板（沪 60x / 深 00x）+ 剔 ST + 剔退市整理股
        self.main_board_only = main_board_only
        self.exclude_st = exclude_st
        # 调仓频率：monthly（月末）/ daily（每日）。
        # 日频模式 select_refresh_days 控制选股池刷新周期（全池选股开销大，
        # 因子以 20/60/120 日窗口为主，日日重选意义有限 → 默认 5 天刷新）
        self.rebalance_freq = rebalance_freq
        self.select_refresh_days = max(1, int(select_refresh_days))
        # 近两日累计买入金额上限（占总资产比例；0=不限）——建仓平滑/防无止境买入
        self.max_buy_2d_pct = float(max_buy_2d_pct or 0.0)
        # 股票元数据（stocks 表：code/name/board/is_st/status/delist_date）
        self._stock_meta = stock_meta
        self._excluded_codes: set[str] | None = None

        # 基本面（point-in-time 面板，由调用方注入；None = 纯价量模式）
        self._fund_input = fundamentals
        self._fund_panels: dict[str, pd.DataFrame] = {}
        self._fund_ready = False

        # 运行时状态
        self._stock_close: dict[str, pd.Series] = {}   # code -> 收盘价序列（后复权）
        self._gold_close: pd.Series | None = None
        self._nasdaq_close: pd.Series | None = None
        self._stock_dates: list = []
        self._last_rebalance_month: tuple | None = None
        self._last_check_date: pd.Timestamp | None = None
        # 近两日买入金额追踪（日频买入限流）：[(date, amount), ...]
        self._buy_log: list[tuple[pd.Timestamp, float]] = []
        # 选股池缓存（日频模式：refresh 周期内复用，省全池选股开销）
        self._selected_pool: list[str] | None = None
        self._selected_pool_date: pd.Timestamp | None = None

    # ------------------------------------------------------------------
    def init(self, context: Context):
        self._stock_close = {}
        self._gold_close = None
        self._nasdaq_close = None
        self._stock_dates = []
        self._last_rebalance_month = None
        self._last_check_date = None
        self._buy_log = []
        self._selected_pool = None
        self._selected_pool_date = None

    def on_bar(self, context: Context, bar: dict):
        """每根 bar 累积数据；月末触发再平衡决策。"""
        code = bar["code"]
        # 后复权口径：因子/择时计算一律用 close×adj_factor（防除权跳空）
        adj = float(bar.get("adj_factor", 1.0) or 1.0)
        close = float(bar["close"]) * adj
        date = pd.to_datetime(bar["date"])

        # 全局交易日轴：任一 bar 到达即推进（每日期只记一次）
        if not self._stock_dates or self._stock_dates[-1] != date:
            self._stock_dates.append(date)

        # 分流：股票 / 黄金 / 纳指
        if code == self.gold_code:
            self._gold_close = self._append(self._gold_close, date, close)
            return
        if code == self.nasdaq_code:
            self._nasdaq_close = self._append(self._nasdaq_close, date, close)
            return

        if self.stock_codes and code not in self.stock_codes:
            return
        self._stock_close[code] = self._append(self._stock_close.get(code), date, close)

        # 月末检查（每日期只判一次：以「本日最后一根股票 bar」近似收盘）
        self._maybe_rebalance(context, date)

    def before_trading(self, context: Context):
        """引擎每日盘前回调：推进全局交易日轴（跨市场对齐）。"""
        # 由引擎注入 current_date（回测/模拟盘统一），兜底用 _stock_dates 尾部
        d = getattr(context, "current_date", None)
        if d is not None:
            d = pd.to_datetime(d)
            if not self._stock_dates or self._stock_dates[-1] != d:
                self._stock_dates.append(d)

    def after_trading(self, context: Context):
        pass

    # ------------------------------------------------------------------
    @staticmethod
    def _append(series: "CrossAssetStrategy._SeriesAcc" | None, date, value: float):
        """追加收盘价：内部用 list 累积（O(1)），用到时才物化为 Series。"""
        if series is None:
            return CrossAssetStrategy._SeriesAcc(date, value)
        series.append(date, value)
        return series

    class _SeriesAcc:
        """收盘价累积器：list 追加 + 惰性物化（大池子性能关键）。"""

        __slots__ = ("dates", "values", "_cache")

        def __init__(self, date, value):
            self.dates = [date]
            self.values = [float(value)]
            self._cache: pd.Series | None = None

        def append(self, date, value):
            self.dates.append(date)
            self.values.append(float(value))
            self._cache = None

        def _materialize(self) -> pd.Series:
            if self._cache is None:
                self._cache = pd.Series(self.values, index=pd.DatetimeIndex(self.dates))
            return self._cache

        def __len__(self):
            return len(self.dates)

        @property
        def index(self):
            return pd.DatetimeIndex(self.dates)

        def iloc(self, i: int) -> float:
            return self.values[i]

        @property
        def last(self) -> float:
            return self.values[-1]

        def pct_change(self, n: int = 1) -> pd.Series:
            return self._materialize().pct_change(n)

        def rolling(self, n: int):
            return self._materialize().rolling(n)

        def to_series(self) -> pd.Series:
            return self._materialize()

    def _maybe_rebalance(self, context: Context, date: pd.Timestamp):
        """按 rebalance_freq 触发再平衡（monthly 月末 / daily 每日；每日期只判一次）。"""
        if self._gold_close is None or self._nasdaq_close is None:
            return
        if len(self._gold_close) < self.lookback or len(self._nasdaq_close) < self.lookback:
            return

        # 本日期已检查过（on_bar 每标的都会触发一次，去重）
        if self._last_check_date == date:
            return
        self._last_check_date = date

        if self.rebalance_freq == "daily":
            self._rebalance(context, date)
            return

        # monthly：月末触发
        if not self._is_month_last_trading_day(date):
            return

        month = (date.year, date.month)
        if self._last_rebalance_month == month:
            return  # 本月已再平衡（防重复）
        self._last_rebalance_month = month
        self._rebalance(context, date)

    def _is_month_last_trading_day(self, date) -> bool:
        """精确月末：全局交易日轴上，下一交易日是否跨月。"""
        axis = self._stock_dates
        if not axis:
            return False
        if axis[-1] == date:
            return True  # 数据末尾视为月末（回测结束前最后一次）
        # 二分查找 date 在轴上的位置
        import bisect
        i = bisect.bisect_left(axis, date)
        if i >= len(axis) or axis[i] != date:
            return False  # 不在轴上（不应发生）
        if i + 1 < len(axis):
            return axis[i + 1].month != date.month
        return True

    # ------------------------------------------------------------------
    def _rebalance(self, context: Context, date: pd.Timestamp):
        """执行再平衡：目标权重 → 目标持仓 → 差额下单（含近两日买入限流）。"""
        total = context.portfolio["total_asset"]
        if total <= 0:
            return

        # 1. 三资产目标权重（λ 并轨）
        weights = self.target_weights()

        # 2. 股票端：多因子打分选股（日频模式：refresh 周期内复用选股池）
        target_stocks = self._get_target_pool(date)

        # 3. 近两日买入限流：剩余可买额度（0=不限）
        buy_cap = self._remaining_buy_budget(context, date)

        stock_budget = total * weights["stock"]
        # 等权预算：先按目标池均分
        per_stock = stock_budget / max(len(target_stocks), 1)
        # 「买得起 1 手」过滤：高价股 1 手市值超单只预算时整只剔除，
        # 防止资金闲置（如预算 3000 元/只而 1 手 5 万元的高价股买不起）
        affordable = [c for c in target_stocks
                      if (p := self._latest_price(c)) and p * 100 <= per_stock * 1.5]
        if len(affordable) < max(self.top_n // 2, 5):
            affordable = target_stocks  # 过滤后过少则退回原池，避免空仓
        per_stock_value = stock_budget / max(len(affordable), 1)

        # 4. 生成调仓订单（差额 → 100 股整数）
        #    买入额度按股票优先、ETF 次序共享同一额度池（order 保序）
        buys: list[tuple[str, float]] = []   # (code, 目标市值)
        self._adjust_position(context, self.gold_code, total * weights["gold"], date,
                              budget_pool=buys, budget_cap=buy_cap)
        self._adjust_position(context, self.nasdaq_code, total * weights["nasdaq"], date,
                              budget_pool=buys, budget_cap=buy_cap)
        for code in affordable:
            self._adjust_position(context, code, per_stock_value, date, band=0.005,
                                  budget_pool=buys, budget_cap=buy_cap)

        # 5. 清仓跌出股票池的持仓（卖出不限流）
        self._cleanup_dropped(context, set(target_stocks), date)

        # 6. 买入金额记账（限流窗口滚动）
        spent = sum(v for _c, v in buys)
        if spent > 0:
            self._buy_log.append((date, spent))
            self._buy_log = [x for x in self._buy_log if x[0] > date - pd.Timedelta(days=4)]

    def _get_target_pool(self, date: pd.Timestamp) -> list[str]:
        """选股池（日频模式 refresh 周期内复用；月频每次重选）。"""
        if self.rebalance_freq != "daily":
            return self.select_stocks(date)
        if (self._selected_pool is not None
                and self._selected_pool_date is not None
                and (date - self._selected_pool_date).days < self.select_refresh_days):
            return self._selected_pool
        pool = self.select_stocks(date)
        self._selected_pool = pool
        self._selected_pool_date = date
        return pool

    def _remaining_buy_budget(self, context: Context, date: pd.Timestamp) -> float:
        """近两日买入限流：剩余可买额度（0=不限）。

        max_buy_2d_pct=0.25 → 任意连续两日累计买入 ≤ 总资产×25%。
        已买金额 = _buy_log 中近两日（自然日）记录之和。
        """
        if self.max_buy_2d_pct <= 0:
            return 0.0  # 不限
        total = context.portfolio["total_asset"]
        cap = total * self.max_buy_2d_pct
        recent = sum(v for d, v in self._buy_log
                     if (date - d).days <= 2)
        return max(cap - recent, 0.0)

    def target_weights(self) -> dict:
        """λ 并轨：最终权重 = 固定 × (1−λ) + 动态择时 × λ。"""
        dynamic = self.dynamic_weights()
        out = {}
        for k in ("stock", "gold", "nasdaq"):
            base = self.base_weights[k]
            dyn = dynamic.get(k, base)
            out[k] = base * (1 - self.lam) + dyn * self.lam
        # 归一化（消除浮点误差）
        s = sum(out.values())
        return {k: v / s for k, v in out.items()}

    def dynamic_weights(self) -> dict:
        """动态择时权重：风险平价 + 动量调整。

        σ_i = 过去 60 日收益标准差 × √252（年化）
        w_i ∝ 1/σ_i（波动率低者权重高）
        m_i = 60 日累计收益，w_i ← w_i × (1 + m_i)
        归一化，裁剪到 [10%, 70%]
        """
        rets = {}
        for k, s in (("stock", self._stock_index_series()),
                     ("gold", self._gold_close.to_series() if self._gold_close is not None else None),
                     ("nasdaq", self._nasdaq_close.to_series() if self._nasdaq_close is not None else None)):
            if s is None or len(s) < self.lookback:
                return dict(self.base_weights)  # 数据不足，退回基准
            r = s.pct_change().dropna().iloc[-self.lookback:]
            rets[k] = r

        sigmas = {k: r.std() * np.sqrt(252) for k, r in rets.items()}
        inv_vol = {k: 1.0 / v if v > 0 else 0.0 for k, v in sigmas.items()}

        # 动量调整
        momentum = {k: float(r.sum()) for k, r in rets.items()}
        adjusted = {k: w * (1.0 + np.clip(m, -0.9, 2.0)) for k, (w, m)
                    in zip(inv_vol.keys(), zip(inv_vol.values(), momentum.values()))}

        total = sum(adjusted.values())
        if total <= 0:
            return dict(self.base_weights)
        w = {k: v / total for k, v in adjusted.items()}

        # 裁剪到 [10%, 70%]
        w = self._clip_weights(w)
        return w

    @staticmethod
    def _clip_weights(w: dict, lo: float = 0.10, hi: float = 0.70) -> dict:
        """投影到 [lo, hi] 且和为 1 的可行集：归一化→裁剪→迭代至可行。"""
        w = {k: float(v) for k, v in w.items()}
        for _ in range(100):
            s = sum(w.values())
            if s <= 0:
                return dict(w)
            w = {k: v / s for k, v in w.items()}
            if all(lo <= v <= hi for v in w.values()):
                return w
            w = {k: min(max(v, lo), hi) for k, v in w.items()}
        return w

    def _stock_index_series(self) -> pd.Series | None:
        """股票端指数代理：等权股票池价格指数（仅用于择时波动率/动量）。"""
        if not self._stock_close:
            return None
        df = pd.DataFrame({code: acc.to_series() for code, acc in self._stock_close.items()})
        df = df.ffill().dropna(how="all")
        if df.empty:
            return None
        return df.mean(axis=1)

    # ------------------------------------------------------------------
    def _prepare_fundamentals(self):
        """惰性构造 point-in-time 基本因子面板（首个再平衡日调用一次）。"""
        if self._fund_ready or self._fund_input is None or self._fund_input.empty:
            self._fund_ready = True
            return
        from data.fundamentals import point_in_time_panel

        fund = self._fund_input.copy()
        fund["report_date"] = pd.to_datetime(fund["report_date"], errors="coerce")
        fund["period"] = pd.to_datetime(fund["period"], errors="coerce")

        # 日期轴：股票池首日 ~ 末日（月频粒度足够，公告滞后以天计）
        dates = pd.date_range(fund["report_date"].min(), fund["report_date"].max(), freq="B")
        for metric in ("roe", "revenue_yoy", "gross_margin"):
            try:
                self._fund_panels[metric] = point_in_time_panel(fund, metric, dates)
            except Exception:  # noqa: BLE001
                continue
        self._fund_ready = True

    def _fund_score(self, code: str, date: pd.Timestamp) -> float | None:
        """单标的的基本面合成分（ROE + 营收增速，z-score 后等权）。"""
        if not self._fund_panels:
            return None
        vals = {}
        for metric in ("roe", "revenue_yoy"):
            panel = self._fund_panels.get(metric)
            if panel is None or code not in panel.columns:
                continue
            # as-of：取 ≤ 当日的最新值
            s = panel[code].dropna()
            s = s[s.index <= date]
            if len(s):
                vals[metric] = float(s.iloc[-1])
        if not vals:
            return None
        return float(np.mean(list(vals.values())))

    def _load_excluded_codes(self) -> set[str]:
        """稳健过滤：构建剔除集合（仅主板模式 + ST + 退市整理）。

        元数据优先用 stocks 表（board/is_st/status/delist_date）；
        无元数据时退化为代码前缀规则（60x 沪主板 / 00x 深主板，
        ST 名称识别需元数据，缺失时按前缀兜底）。
        """
        if self._excluded_codes is not None:
            return self._excluded_codes
        excluded: set[str] = set()

        def _is_main_board(code: str) -> bool:
            # 沪主板 600/601/603/605，深主板 000/001/002/003；创业板/科创板/北交所均非主板
            return code.startswith(("600", "601", "603", "605", "000", "001", "002", "003"))

        if self._stock_meta is not None and len(self._stock_meta):
            df = self._stock_meta
            for _, row in df.iterrows():
                code = str(row.get("code", ""))
                if not code:
                    continue
                board = str(row.get("board", "")).lower()
                if self.main_board_only and board != "main":
                    excluded.add(code)
                    continue
                if self.exclude_st and (row.get("is_st") == 1 or
                                        str(row.get("name", "")).upper().find("ST") >= 0):
                    excluded.add(code)
                    continue
                # 退市整理股：名称含「退」（萃华退/退市银鸽等），柜台禁买 [251125]
                if self.exclude_st and "退" in str(row.get("name", "")):
                    excluded.add(code)
                    continue
                # 已退市/退市整理（status=delisted 或 delist_date 非空且已过）
                status = str(row.get("status", "")).lower()
                if status == "delisted":
                    excluded.add(code)
        else:
            # 无元数据兜底：仅用代码规则
            if self.main_board_only:
                excluded = {c for c in self.stock_codes if not _is_main_board(c)}

        self._excluded_codes = excluded
        return excluded

    def select_stocks(self, date: pd.Timestamp | None = None) -> list[str]:
        """A 股 Alpha 端：多因子打分 → top N。

        因子（价量组）：动量(20/60/120d) + 波动率(逆向) + 反转(5d)
        因子（基本面组，财报数据可用时）：ROE + 营收增速（point-in-time）
        合成：组内 z-score 等权 → 组间等权。等权起步，进阶可按历史 IC 加权。
        """
        if not self._stock_close:
            return []
        self._prepare_fundamentals()

        # 稳健过滤：仅主板 + 剔 ST + 剔退市整理股（元数据 stocks 表 point-in-time）；
        # 创业板/科创板按账户权限开关剔除（未开通权限必废单）
        excluded = self._load_excluded_codes()

        def _market_ok(code: str) -> bool:
            if code in excluded:
                return False
            if not self.main_board_only:
                # 非仅主板模式仍按权限过滤创业板/科创板
                if code.startswith(("300", "301")):
                    return self.allow_chinext
                if code.startswith("688"):
                    return self.allow_star
            return True

        # 构造截面因子值：每个 code 的最新因子值
        scores: dict[str, dict] = {}
        for code, s in self._stock_close.items():
            if not _market_ok(code):
                continue
            if len(s) < 120:
                continue
            # 纯 Python 计算尾部因子值（避免整列 pct_change 的开销）
            vals = s.values
            closes = vals[-121:]
            if len(closes) < 121 or any(v <= 0 for v in closes):
                continue

            def _pct(n: int) -> float:
                return closes[-1] / closes[-1 - n] - 1.0

            mom20 = _pct(20)
            mom60 = _pct(60)
            mom120 = _pct(120)
            rev5 = -_pct(5)
            # 20 日收益波动率
            rets20 = [closes[i + 1] / closes[i] - 1.0 for i in range(len(closes) - 21, len(closes) - 1)]
            mean_r = sum(rets20) / len(rets20)
            var_r = sum((r - mean_r) ** 2 for r in rets20) / (len(rets20) - 1)
            vol20 = var_r ** 0.5
            # 方向修正（2026-11 全池 IC 质检 report/qa/fullpool_ic.csv）：
            # A 股动量因子 21 日 IC≈-0.04（反转市场）→ 取负买跌得反转；
            # 低波动溢价 IC(vol)≈-0.047 → 取负买低波
            row = {"mom20": -mom20, "mom60": -mom60, "mom120": -mom120,
                   "rev5": rev5, "vol20": -vol20}
            # 基本面合成分（point-in-time）
            if date is not None and self._fund_panels:
                fs = self._fund_score(code, date)
                if fs is not None:
                    row["fund"] = fs
            scores[code] = row
        if len(scores) < self.top_n:
            top_codes = list(scores.keys())
        else:
            df = pd.DataFrame(scores).T
            # 截面 z-score（波动率逆向：低波动加分）
            z = df.apply(lambda col: zscore(col))
            composite = z.mean(axis=1)  # 等权合成
            top_codes = composite.sort_values(ascending=False).head(self.top_n).index.tolist()
        return top_codes

    # ------------------------------------------------------------------
    def _adjust_position(self, context: Context, code: str, target_value: float, date,
                        band: float = 0.02, budget_pool: list | None = None,
                        budget_cap: float = 0.0):
        """调仓到目标市值（差额 → 100 股整数），带再平衡阈值。

        band: 最小调仓阈值（占单只持仓目标/当前市值比例，控制换手）。
        ETF 端 2%；股票端调用方传 0.005。

        budget_pool/budget_cap: 近两日买入限流。budget_cap>0 时，本单买入
        金额记入 budget_pool，累计超限部分缩减（超限则截断到手数最小单位，
        为 0 则跳过）。卖出不受限。
        """
        price = self._latest_price(code)
        if price is None or price <= 0:
            return
        pos = context.portfolio["positions"].get(code)
        cur_value = pos["market_value"] if pos else 0.0

        diff = target_value - cur_value
        # 最小调仓阈值：相对 max(目标, 当前) 持仓市值（而非总资产）。
        # 若按总资产算，小市值分仓（如单只 3000 元）会被整体跳过 → 结构性空仓。
        if abs(diff) < band * max(target_value, cur_value, 1.0):
            return

        # 手数规则：科创板最低 200 股、其余 100 股（柜台硬性校验，
        # 100 股的科创板单必废 [120156]）
        lot = 200 if code.startswith("688") else 100
        lots = int(abs(diff) / price / lot) * lot
        if lots <= 0:
            return
        if diff > 0:
            # 买入限流：剩余额度不足时缩减手数（不足 1 手则跳过）
            if budget_pool is not None and budget_cap > 0:
                already = sum(v for _c, v in budget_pool)
                avail = budget_cap - already
                buy_value = lots * price
                if buy_value > avail:
                    lots = int(avail / price / lot) * lot
                    if lots <= 0:
                        return  # 额度耗尽，本单跳过（次日额度恢复继续买）
                if lots > 0:
                    budget_pool.append((code, lots * price))
            if lots > 0:
                context.buy(code, price, lots)
        else:
            vol = min(lots, pos["volume"] if pos else 0)
            if vol > 0:
                context.sell(code, price, vol)

    def _cleanup_dropped(self, context: Context, keep: set[str], date):
        """清仓跌出股票池的股票持仓。"""
        for code, pos in list(context.portfolio["positions"].items()):
            if code in (self.gold_code, self.nasdaq_code):
                continue
            if code not in keep:
                price = self._latest_price(code)
                if price and pos["volume"] > 0:
                    context.sell(code, price, pos["volume"])

    def _latest_price(self, code: str) -> float | None:
        if code == self.gold_code:
            s = self._gold_close
        elif code == self.nasdaq_code:
            s = self._nasdaq_close
        else:
            s = self._stock_close.get(code)
        if s is None or len(s) == 0:
            return None
        return float(s.last)
