"""
参数优化（M4）

红线：
1. 强制 Walk-Forward：训练段选参数，测试段验证，两段分离。
   禁止在全部数据上选最优参数后直接报成绩。
2. 输出参数稳健性（邻域敏感度）：最优点附近参数小幅变动，绩效不应悬崖式下跌。

实现：网格搜索起步。optimize() 返回训练段最优参数 + 测试段真实成绩。
"""

from __future__ import annotations

import itertools

import pandas as pd


class WalkForwardOptimizer:
    """Walk-Forward 参数优化器。

    用法：
        opt = WalkForwardOptimizer(make_strategy, param_grid, metric="sharpe")
        report = opt.optimize(bars)
    """

    def __init__(self, make_strategy, param_grid: dict, metric: str = "sharpe"):
        """
        params
        ------
        make_strategy : callable(**params) -> Strategy
        param_grid : {param_name: [values]} 网格
        metric : 优化目标（sharpe / total_return / calmar）
        """
        self.make_strategy = make_strategy
        self.param_grid = param_grid
        self.metric = metric

    def _grid(self) -> list[dict]:
        keys = list(self.param_grid.keys())
        for values in itertools.product(*[self.param_grid[k] for k in keys]):
            yield dict(zip(keys, values))

    def _run(self, strategy, bars) -> dict:
        """跑一次回测，返回绩效 dict。"""
        from backtest.engine import BacktestEngine
        engine = BacktestEngine(strategy=strategy)
        result = engine.run(bars)
        return result.metrics

    def optimize(
        self,
        bars: dict[str, pd.DataFrame],
        train_ratio: float = 0.7,
    ) -> dict:
        """Walk-Forward 优化：训练段网格搜索 → 最优参数 → 测试段验证。

        参数按时间切分 bars（train_ratio 之前为训练段，之后为测试段）。
        返回 {best_params, train_score, test_score, all_train_scores, stability}
        """
        # 时间切分
        all_dates = sorted(set().union(*[
            set(pd.to_datetime(df["date"]).dt.normalize()) for df in bars.values()
        ]))
        if len(all_dates) < 40:
            raise ValueError("数据太短，无法 Walk-Forward（至少 40 个交易日）")
        split = all_dates[int(len(all_dates) * train_ratio)]
        train_bars = {
            code: df[pd.to_datetime(df["date"]).dt.normalize() <= split]
            for code, df in bars.items()
        }
        test_bars = {
            code: df[pd.to_datetime(df["date"]).dt.normalize() > split]
            for code, df in bars.items()
        }

        # 训练段网格搜索
        results = []
        for params in self._grid():
            try:
                metrics = self._run(self.make_strategy(**params), train_bars)
                results.append({"params": params, "score": metrics.get(self.metric, float("-inf"))})
            except Exception as e:  # noqa: BLE001
                results.append({"params": params, "score": float("-inf"), "error": str(e)[:80]})

        results.sort(key=lambda r: r["score"], reverse=True)
        best = results[0]

        # 测试段验证（样本外）
        test_metrics = self._run(self.make_strategy(**best["params"]), test_bars)

        # 邻域稳健性：最优点附近一格的参数，训练段绩效变化
        stability = self._neighborhood_stability(best, results)

        return {
            "best_params": best["params"],
            "train_score": best["score"],
            "test_score": test_metrics.get(self.metric, float("-inf")),
            "test_metrics": test_metrics,
            "all_train_scores": results,
            "stability": stability,
        }

    def _neighborhood_stability(self, best: dict, all_results: list[dict]) -> dict:
        """邻域敏感度：最优点 vs 邻点训练绩效。"""
        best_params = best["params"]
        neighbors = []
        for r in all_results:
            if r is best:
                continue
            diff_count = sum(
                1 for k in best_params
                if r["params"].get(k) != best_params.get(k)
            )
            if diff_count == 1:  # 单参数相邻
                neighbors.append(r)

        if not neighbors:
            return {"n_neighbors": 0, "score_drop_ratio": None}

        neighbor_scores = [r["score"] for r in neighbors if r["score"] > float("-inf")]
        if not neighbor_scores or best["score"] <= float("-inf"):
            return {"n_neighbors": len(neighbors), "score_drop_ratio": None}

        max_neighbor = max(neighbor_scores)
        drop_ratio = float((best["score"] - max_neighbor) / abs(best["score"])) \
            if best["score"] != 0 else 0.0
        return {
            "n_neighbors": len(neighbors),
            "max_neighbor_score": max_neighbor,
            "score_drop_ratio": round(drop_ratio, 4),
        }
