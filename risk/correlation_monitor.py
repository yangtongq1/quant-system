"""
相关性监控模块（风控 · 分散失效监控）

职责：监控三资产（股票/黄金/纳指）的滚动相关性，检测「分散失效」——
纳指/黄金与 A 股相关性突变为正时告警。

实证依据（2013–2026 实测）：纳指-A股整体相关 0.235，但 2020 疫情飙到 0.69（同跌），
说明相关性是时变的，必须持续监控，而非只看历史均值。
"""

from __future__ import annotations

import pandas as pd


class CorrelationMonitor:
    """滚动相关性监控。

    阈值参考：纳指-A股相关性 0.5 预警（分散效果减弱）、0.7 告警（对冲失效，接近 2020 疫情 0.69）。
    """

    def __init__(self, window: int = 60, warn: float = 0.5, alert: float = 0.7):
        self.window = window
        self.warn = warn
        self.alert = alert

    def monitor(self, prices: pd.DataFrame) -> pd.DataFrame:
        """输入价格 DataFrame（须含列 stock/gold/nasdaq，date 索引），输出滚动相关系数。

        返回列：gold_stock_corr / nasdaq_stock_corr（窗口内日收益相关系数）。
        """
        ret = prices[["stock", "gold", "nasdaq"]].pct_change().dropna()
        out = pd.DataFrame(index=ret.index)
        out["gold_stock_corr"] = ret["gold"].rolling(self.window).corr(ret["stock"])
        out["nasdaq_stock_corr"] = ret["nasdaq"].rolling(self.window).corr(ret["stock"])
        return out

    def check_latest(self, prices: pd.DataFrame) -> dict:
        """检查最新一期相关性，返回告警信息 dict。"""
        corr = self.monitor(prices)
        latest = corr.iloc[-1] if len(corr) else None
        if latest is None or pd.isna(latest["nasdaq_stock_corr"]):
            return {"date": None, "status": "ok", "alerts": []}

        ndx = float(latest["nasdaq_stock_corr"])
        gold = float(latest["gold_stock_corr"])
        alerts: list[str] = []

        if ndx >= self.alert:
            alerts.append(f"纳指-A股相关性 {ndx:.2f} 超告警线 {self.alert}（对冲失效风险）")
        elif ndx >= self.warn:
            alerts.append(f"纳指-A股相关性 {ndx:.2f} 超预警线 {self.warn}（分散效果减弱）")

        if gold >= self.warn:
            alerts.append(f"黄金-A股相关性 {gold:.2f} 超预警线 {self.warn}（避险属性减弱）")

        return {
            "date": str(corr.index[-1].date()),
            "gold_stock_corr": round(gold, 3),
            "nasdaq_stock_corr": round(ndx, 3),
            "status": "alert" if alerts else "ok",
            "alerts": alerts,
        }
