"""
因子计算引擎（M3）

职责：批量计算因子库中所有因子，输出面板数据（行=日期，列=标的）或长表。
每个因子是「单标的时序函数」：输入该标的日线，输出按日期索引的因子值。
引擎统一调度：截面面板化 + 增量更新缓存。
"""

from __future__ import annotations

import pandas as pd


# 因子注册表：名字 → 计算函数
_FACTOR_REGISTRY: dict[str, callable] = {}


def register_factor(name: str):
    """装饰器：注册因子。因子函数签名 df(bars) -> pd.Series（索引=date）。"""
    def decorator(func):
        _FACTOR_REGISTRY[name] = func
        return func
    return decorator


def list_factors() -> list[str]:
    """已注册因子清单。"""
    # 触发导入，让装饰器注册
    from factors.library import momentum, volatility, value, quality  # noqa: F401
    return sorted(_FACTOR_REGISTRY.keys())


class FactorEngine:
    """因子计算引擎。

    输入 bars: {code: 日线 DataFrame}
    输出 panel: {factor_name: DataFrame(行=date, 列=code)}
    """

    def __init__(self, bars: dict[str, pd.DataFrame] | None = None):
        self.bars = bars or {}
        self._cache: dict[str, pd.DataFrame] = {}

    def set_bars(self, bars: dict[str, pd.DataFrame]):
        self.bars = bars
        self._cache = {}

    def compute(self, factor_name: str) -> pd.DataFrame:
        """计算单因子，返回截面面板（行=date, 列=code）。结果缓存。"""
        from factors.library import momentum, volatility, value, quality  # noqa: F401
        if factor_name in self._cache:
            return self._cache[factor_name]
        if factor_name not in _FACTOR_REGISTRY:
            raise KeyError(f"未注册因子: {factor_name}，可选: {list_factors()}")

        panels: dict[str, pd.Series] = {}
        for code, df in self.bars.items():
            df = df.copy()
            df["date"] = pd.to_datetime(df["date"])
            series = _FACTOR_REGISTRY[factor_name](df)
            if series is not None and len(series):
                panels[code] = pd.Series(series.values, index=series.index)

        if not panels:
            return pd.DataFrame()
        panel = pd.DataFrame(panels)
        self._cache[factor_name] = panel
        return panel

    def compute_all(self, names: list[str] | None = None) -> dict[str, pd.DataFrame]:
        """批量计算因子（默认全部注册因子）。"""
        names = names or list_factors()
        return {name: self.compute(name) for name in names}
