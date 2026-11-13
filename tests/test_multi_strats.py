"""多策略体系测试：等权/风险平价/纯股票/ETF 轮动"""
from __future__ import annotations

import numpy as np
import pandas as pd

from strategy.cross_asset import CrossAssetStrategy


def _to_acc(series: pd.Series):
    acc = CrossAssetStrategy._SeriesAcc(series.index[0], float(series.iloc[0]))
    for d, v in zip(series.index[1:], series.values[1:]):
        acc.append(d, float(v))
    return acc


def _make_market(n=200, seed=1):
    """构造三资产合成行情。"""
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2025-01-01", periods=n, freq="B")
    stock = 10 * np.cumprod(1 + rng.normal(0.001, 0.015, n))
    gold = 5 * np.cumprod(1 + rng.normal(0.0005, 0.008, n))
    nasdaq = 2 * np.cumprod(1 + rng.normal(0.0012, 0.02, n))
    return dates, stock, gold, nasdaq


def test_equal_weight_weights():
    """等权：三资产恒 1/3。"""
    from strategy.multi import EqualWeightStrategy
    dates, stock, gold, nasdaq = _make_market()
    s = EqualWeightStrategy(top_n=10)
    s._stock_close = {"600000": _to_acc(pd.Series(stock, index=dates))}
    s._gold_close = _to_acc(pd.Series(gold, index=dates))
    s._nasdaq_close = _to_acc(pd.Series(nasdaq, index=dates))
    w = s.target_weights()
    assert abs(w["stock"] - 1/3) < 1e-9
    assert abs(w["gold"] - 1/3) < 1e-9
    assert abs(sum(w.values()) - 1.0) < 1e-9
    # λ 强制为 0（纯基准）
    assert s.lam == 0.0


def test_risk_parity_weights():
    """风险平价：权重 ∝ 1/σ，和为 1，无裁剪（可超 70%）。"""
    from strategy.multi import RiskParityStrategy
    dates, stock, gold, nasdaq = _make_market(seed=2)
    s = RiskParityStrategy(top_n=10)
    s._stock_close = {"600000": _to_acc(pd.Series(stock, index=dates))}
    s._gold_close = _to_acc(pd.Series(gold, index=dates))
    s._nasdaq_close = _to_acc(pd.Series(nasdaq, index=dates))
    w = s.target_weights()
    assert abs(sum(w.values()) - 1.0) < 1e-9
    # 黄金波动最低 → 权重最高
    assert w["gold"] > w["nasdaq"]
    # 无裁剪：允许极端权重（这里用低波动种子验证 gold 可超过 0.70——若
    # 波动差异不够极端则放宽为 >0.5，检验「无 10% 下限」不成立即可）
    assert w["gold"] > 0.5 or w["stock"] > 0.5 or w["nasdaq"] > 0.5


def test_risk_parity_no_clip():
    """风险平价无 [10%,70%] 裁剪：构造极端波动差验证可突破 70%。"""
    from strategy.multi import RiskParityStrategy
    n = 200
    dates = pd.date_range("2025-01-01", periods=n, freq="B")
    rng = np.random.default_rng(7)
    s = RiskParityStrategy(top_n=10)
    s._stock_close = {"600000": _to_acc(pd.Series(
        10 * np.cumprod(1 + rng.normal(0, 0.05, n)), index=dates))}   # 极高波动
    s._gold_close = _to_acc(pd.Series(
        5 + rng.normal(0, 0.0005, n).cumsum(), index=dates))          # 极低波动
    s._nasdaq_close = _to_acc(pd.Series(
        2 * np.cumprod(1 + rng.normal(0, 0.04, n)), index=dates))    # 高波动
    w = s.target_weights()
    # 无裁剪：gold 应获得远超 70% 的权重
    assert w["gold"] > 0.70, f"gold={w['gold']:.3f} 应无 70% 上限"


def test_stock_only_weights():
    """纯股票：stock=1.0，gold/nasdaq=0。"""
    from strategy.multi import StockOnlyStrategy
    dates, stock, gold, nasdaq = _make_market(seed=3)
    s = StockOnlyStrategy(top_n=10)
    s._stock_close = {"600000": _to_acc(pd.Series(stock, index=dates))}
    s._gold_close = _to_acc(pd.Series(gold, index=dates))
    s._nasdaq_close = _to_acc(pd.Series(nasdaq, index=dates))
    w = s.target_weights()
    assert w["stock"] == 1.0
    assert w["gold"] == 0.0
    assert w["nasdaq"] == 0.0


def test_etf_momentum_end_to_end():
    """ETF 轮动端到端：构造上涨黄金/下跌股票，策略应全仓黄金。"""
    from backtest.engine import BacktestEngine
    from strategy.multi import ETFMomentumStrategy

    n = 160
    dates = pd.date_range("2025-01-01", periods=n, freq="B")
    # 黄金持续上涨（60日动量>0），股票持续下跌（动量<0），纳指下跌
    gold = pd.DataFrame({
        "date": dates, "open": np.linspace(5, 8, n), "high": np.linspace(5, 8, n),
        "low": np.linspace(5, 8, n), "close": np.linspace(5, 8, n),
        "volume": [1e6] * n, "adj_factor": [1.0] * n, "is_trading": [1] * n,
    })
    stock = pd.DataFrame({
        "date": dates, "open": np.linspace(4, 3, n), "high": np.linspace(4, 3, n),
        "low": np.linspace(4, 3, n), "close": np.linspace(4, 3, n),
        "volume": [1e6] * n, "adj_factor": [1.0] * n, "is_trading": [1] * n,
    })
    nasdaq = pd.DataFrame({
        "date": dates, "open": np.linspace(2, 1.5, n), "high": np.linspace(2, 1.5, n),
        "low": np.linspace(2, 1.5, n), "close": np.linspace(2, 1.5, n),
        "volume": [1e6] * n, "adj_factor": [1.0] * n, "is_trading": [1] * n,
    })
    strat = ETFMomentumStrategy(
        etf_codes=["518880", "510300", "513100"],
        momentum_window=30,   # 测试用短窗口
    )
    engine = BacktestEngine(strategy=strat, initial_cash=1_000_000)
    result = engine.run({"518880": gold, "510300": stock, "513100": nasdaq})

    # 黄金上涨 → 期末持仓应以 518880 为主
    final_positions = list(engine.broker.positions.keys())
    assert "518880" in final_positions, f"期末应持有黄金: {final_positions}"
    # 黄金从 5 涨到 8，持仓存在则净值应上涨
    assert result.metrics["total_return"] > 0, f"黄金上涨行情收益应为正: {result.metrics}"
    # 股票/纳指下跌 → 不应持有
    assert "510300" not in final_positions
    assert "513100" not in final_positions


def test_etf_momentum_all_negative_cash_fallback():
    """ETF 轮动全负动量：持动量最高一只（防踏空），不空仓。"""
    from backtest.engine import BacktestEngine
    from strategy.multi import ETFMomentumStrategy

    n = 160
    dates = pd.date_range("2025-01-01", periods=n, freq="B")
    # 三只全下跌，黄金跌最慢（动量最高）
    mk = lambda a, b: pd.DataFrame({  # noqa: E731
        "date": dates, "open": np.linspace(a, b, n), "high": np.linspace(a, b, n),
        "low": np.linspace(a, b, n), "close": np.linspace(a, b, n),
        "volume": [1e6] * n, "adj_factor": [1.0] * n, "is_trading": [1] * n,
    })
    strat = ETFMomentumStrategy(
        etf_codes=["518880", "510300", "513100"], momentum_window=30)
    engine = BacktestEngine(strategy=strat, initial_cash=1_000_000)
    result = engine.run({
        "518880": mk(5, 4.5),   # -10%（跌最慢，动量最高）
        "510300": mk(4, 2.0),   # -50%
        "513100": mk(2, 1.0),   # -50%
    })
    positions = list(engine.broker.positions.keys())
    assert positions == ["518880"], f"应只持跌最慢的黄金: {positions}"
    assert result.metrics["total_return"] < 0  # 行情全跌，净值必然为负


def test_strategy_registry_cli():
    """CLI 注册表：backtest --strategy choices 含新策略 + all。"""
    import ast
    import pathlib
    main_src = pathlib.Path("main.py").read_text(encoding="utf-8")
    tree = ast.parse(main_src)
    # 找 backtest 子命令的 choices（含 "all" 的那个；run-paper 的不含 all）
    found = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "attr", "") == "add_argument":
            for kw in node.keywords:
                if kw.arg == "choices" and "cross_asset" in ast.unparse(kw.value):
                    choices = ast.literal_eval(kw.value)
                    if "all" not in choices:
                        continue  # run-paper 的 choices，跳过
                    assert "equal_weight" in choices and "risk_parity" in choices
                    assert "stock_only" in choices and "etf_momentum" in choices
                    found = True
    assert found, "backtest --strategy choices 应包含新策略 + all"
