"""
图表模块（M6 报告层）：净值/回撤曲线、月度收益热力图
"""

from __future__ import annotations

from pathlib import Path

import matplotlib
matplotlib.use("Agg")  # 无界面环境
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

# 中文字体（Windows 自带微软雅黑；缺字体时自动退化为英文标签）
plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False


def plot_equity_curves(
    equities: dict[str, pd.Series],
    out_path: str | Path = "report/equity.png",
    title: str = "净值曲线",
    log_scale: bool = False,
) -> Path:
    """多策略净值对比曲线（归一化到 1）。"""
    fig, ax = plt.subplots(figsize=(10, 5), dpi=120)
    for name, eq in equities.items():
        eq = pd.Series(eq, dtype=float).dropna()
        if len(eq) < 2:
            continue
        norm = eq / eq.iloc[0]
        ax.plot(eq.index, norm.values, label=name, linewidth=1.4)
    ax.set_title(title)
    ax.set_ylabel("净值")
    ax.legend(loc="best")
    ax.grid(alpha=0.3)
    if log_scale:
        ax.set_yscale("log")
    fig.tight_layout()
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path)
    plt.close(fig)
    return Path(out_path)


def plot_drawdown(
    equity: pd.Series,
    out_path: str | Path = "report/drawdown.png",
    title: str = "回撤曲线",
) -> Path:
    """回撤曲线（填充面积图）。"""
    eq = pd.Series(equity, dtype=float).dropna()
    dd = eq / eq.cummax() - 1.0
    fig, ax = plt.subplots(figsize=(10, 3.5), dpi=120)
    ax.fill_between(dd.index, dd.values * 100, 0, color="#c0392b", alpha=0.45)
    ax.set_title(title)
    ax.set_ylabel("回撤 (%)")
    ax.grid(alpha=0.3)
    fig.tight_layout()
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path)
    plt.close(fig)
    return Path(out_path)


def plot_monthly_returns_heatmap(
    equity: pd.Series,
    out_path: str | Path = "report/monthly.png",
    title: str = "月度收益热力图",
) -> Path:
    """月度收益热力图（行=年份，列=月份）。"""
    eq = pd.Series(equity, dtype=float).dropna()
    if len(eq) < 20:
        raise ValueError("数据不足")
    monthly = eq.resample("ME").last()
    ret = monthly.pct_change()
    # 首月收益需用首日
    if len(eq) > 0:
        first_month_end = monthly.index[0]
        first_val = eq[eq.index <= first_month_end]
        if len(first_val) > 1:
            ret.iloc[0] = first_val.iloc[-1] / first_val.iloc[0] - 1.0

    pivot = pd.DataFrame({
        "year": ret.index.year,
        "month": ret.index.month,
        "ret": ret.values * 100,
    }).pivot_table(index="year", columns="month", values="ret")

    fig, ax = plt.subplots(figsize=(11, max(3, 0.55 * len(pivot))), dpi=120)
    vmax = float(np.nanmax(np.abs(pivot.values))) or 5.0
    im = ax.imshow(pivot.values, cmap="RdYlGn_r", vmin=-vmax, vmax=vmax, aspect="auto")
    ax.set_xticks(range(len(pivot.columns)), [f"{m}月" for m in pivot.columns])
    ax.set_yticks(range(len(pivot.index)), pivot.index)
    # 单元格数值标注
    for i in range(pivot.shape[0]):
        for j in range(pivot.shape[1]):
            v = pivot.iloc[i, j]
            if pd.notna(v):
                ax.text(j, i, f"{v:.1f}", ha="center", va="center", fontsize=8,
                        color="black" if abs(v) < vmax * 0.6 else "white")
    ax.set_title(title)
    fig.colorbar(im, ax=ax, shrink=0.8, label="月收益 (%)")
    fig.tight_layout()
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path)
    plt.close(fig)
    return Path(out_path)
