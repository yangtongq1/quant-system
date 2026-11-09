# -*- coding: utf-8 -*-
"""全池因子 IC 质检：复用策略截面因子逻辑，检验真实选股因子的预测力。

用法: python scripts/factor_ic_fullpool.py [--top-n 800] [--start 2018-01-01]
抽样 top-n 只（按最新市值排序，流动性好的优先）以控制运行时间。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.config import load_config  # noqa: E402

CONFIG = load_config()


def zscore(s: pd.Series) -> pd.Series:
    return (s - s.mean()) / (s.std() + 1e-12)


def build_panels(bars: dict[str, pd.DataFrame], start: str) -> dict[str, pd.DataFrame]:
    """价量因子面板：每个因子一张 日期×股票 的 DataFrame。"""
    closes: dict[str, pd.Series] = {}
    for code, df in bars.items():
        idx = pd.to_datetime(df["date"].to_numpy())
        vals = (df["close"] * df["adj_factor"]).to_numpy()
        closes[code] = pd.Series(vals, index=idx)

    close_df = pd.DataFrame(closes)
    close_df = close_df.loc[close_df.index >= pd.Timestamp(start)]

    panels = {
        "mom20": close_df.pct_change(20),
        "mom60": close_df.pct_change(60),
        "mom120": close_df.pct_change(120),
        "rev5": -close_df.pct_change(5),
        "vol20": close_df.pct_change().rolling(20).std(),
    }
    return panels


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--top-n", type=int, default=800,
                        help="抽样股票数（按成交额排序取流动性最好的 N 只）")
    parser.add_argument("--start", default="2018-01-01")
    parser.add_argument("--end", default="2026-11-05")
    args = parser.parse_args()

    bars_dir = ROOT / CONFIG["data"]["bars_dir"]
    # 按最新成交额取流动性前 N 的股票（控制规模同时保证截面代表性）
    stats = []
    for p in bars_dir.glob("*.parquet"):
        code = p.stem
        if code in ("518880", "513100"):
            continue
        try:
            df = pd.read_parquet(p, columns=["volume", "close"])
            last_amt = float(df["volume"].iloc[-1] * df["close"].iloc[-1]) if len(df) else 0.0
        except Exception:  # noqa: BLE001
            continue
        stats.append((code, last_amt))
    stats.sort(key=lambda x: x[1], reverse=True)
    codes = [c for c, _ in stats[: args.top_n]]
    print(f"[qa] 抽样 {len(codes)} 只（成交额 top {args.top_n}）")

    bars = {}
    for code in codes:
        p = bars_dir / f"{code}.parquet"
        try:
            df = pd.read_parquet(p)
            df = df[(df["date"] >= args.start) & (df["date"] <= args.end)]
            if len(df) > 130:
                bars[code] = df
        except Exception:  # noqa: BLE001
            continue
    print(f"[qa] 有效 {len(bars)} 只")

    panels = build_panels(bars, args.start)
    # 下期收益（月频前瞻收益：t→t+21 交易日）
    closes = {}
    for code, df in bars.items():
        idx = pd.to_datetime(df["date"].to_numpy())
        vals = (df["close"] * df["adj_factor"]).to_numpy()
        closes[code] = pd.Series(vals, index=idx)
    close_df = pd.DataFrame(closes)
    ret_panel = close_df.pct_change().shift(-1)  # t+1 日收益（参考）

    # 策略真实持有期收益：t → t+21 交易日（月度调仓持有期）
    fwd21 = close_df.shift(-21) / close_df - 1.0

    # 月末截面（与策略调仓频率一致）：每月最后一个交易日
    month_last = close_df.index.to_series().groupby(
        [close_df.index.year, close_df.index.month]).max()

    rows = []
    for name, panel in panels.items():
        ics = []
        for d in month_last:
            if d not in panel.index:
                continue
            f = panel.loc[d].dropna()
            if len(f) < 50:
                continue
            r = fwd21.loc[d].dropna() if d in fwd21.index else pd.Series(dtype=float)
            common = f.index.intersection(r.index)
            if len(common) < 50:
                continue
            ic = f[common].corr(r[common], method="spearman")
            if pd.notna(ic):
                ics.append(ic)
        ics = pd.Series(ics)
        if len(ics) == 0:
            print(f"[qa] {name}: 无有效截面")
            continue
        ic_mean = ics.mean()
        icir = ics.mean() / ics.std() if ics.std() > 0 else np.nan
        ic_win = (ics > 0).mean()
        rows.append({
            "factor": name,
            "ic_mean": round(ic_mean, 4),
            "icir": round(icir, 4) if pd.notna(icir) else None,
            "ic_win_rate": round(ic_win, 4),
            "n_sections": len(ics),
        })
        print(f"[qa] {name}: IC={ic_mean:+.4f}  ICIR={icir:+.3f}  胜率={ic_win:.1%}  截面数={len(ics)}")

    # 基本面因子（ROE / 营收增速）—— point-in-time 截面
    try:
        import sqlite3
        con = sqlite3.connect(ROOT / CONFIG["data"]["db_path"])
        fund = pd.read_sql(
            "select code, report_date, roe, revenue_yoy from fundamentals", con)
        fund["report_date"] = pd.to_datetime(fund["report_date"])
        fund = fund.dropna(subset=["roe", "revenue_yoy"])
        for fac_name, col in [("fund_roe", "roe"), ("fund_rev_yoy", "revenue_yoy")]:
            ics = []
            for d in month_last:
                # point-in-time: 只用 report_date <= d 的每只股票最新记录
                sub = fund[fund["report_date"] <= d]
                if sub.empty:
                    continue
                latest = sub.sort_values("report_date").groupby("code").tail(1)
                latest = latest.set_index("code")[col]
                latest = latest[latest.index.intersection(close_df.columns)]
                if len(latest) < 50:
                    continue
                r = fwd21.loc[d].dropna() if d in fwd21.index else pd.Series(dtype=float)
                common = latest.index.intersection(r.index)
                if len(common) < 50:
                    continue
                ic = latest[common].corr(r[common], method="spearman")
                if pd.notna(ic):
                    ics.append(ic)
            ics = pd.Series(ics)
            if len(ics):
                icir = ics.mean() / ics.std() if ics.std() > 0 else np.nan
                rows.append({
                    "factor": fac_name,
                    "ic_mean": round(ics.mean(), 4),
                    "icir": round(icir, 4) if pd.notna(icir) else None,
                    "ric_win_rate": None,
                    "n_sections": len(ics),
                })
                print(f"[qa] {fac_name}: IC={ics.mean():+.4f}  ICIR={icir:+.3f}  截面数={len(ics)}")
    except Exception as e:  # noqa: BLE001
        print(f"[qa] 基本面因子质检跳过: {e}")

    out = ROOT / "report" / "qa" / "fullpool_ic.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(out, index=False, encoding="utf-8-sig")
    print(f"\n[qa] 结果已存 {out}")


if __name__ == "__main__":
    main()
