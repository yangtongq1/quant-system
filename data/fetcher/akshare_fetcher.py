"""
akshare 数据源实现（M1 数据采集样例，可跑通）

数据源选择：
- 股票日线：新浪 stock_zh_a_daily（英文列名 date/open/high/low/close/volume/amount）
- ETF 日线：新浪 fund_etf_hist_sina
- 交易日历：tool_trade_date_hist_sina
- 股票列表：stock_info_a_code_name（存续）+ stock_info_sh_delist / sz_delist（退市）

注意：东方财富系接口（stock_zh_a_hist、fund_etf_hist_em）易被限流，已避开。
"""

from __future__ import annotations

import time

import akshare as ak
import pandas as pd

from data.fetcher.base import DataFetcher


def _retry(func, times: int = 3, delay: float = 3.0):
    """对不稳定的数据源接口做重试，失败返回 None。"""
    last = None
    for i in range(times):
        try:
            return func()
        except Exception as e:  # noqa: BLE001
            last = e
            if i < times - 1:
                time.sleep(delay)
    print(f"[fetcher] 重试 {times} 次后仍失败: {type(last).__name__} {str(last)[:120]}")
    return None


def to_sina_symbol(code: str) -> str:
    """标的代码 → 新浪符号（带交易所前缀）。

    - 6/9 开头：沪市股票
    - 0/3 开头：深市股票
    - 8/4 开头：北交所
    - 5 开头：沪市 ETF/基金（如 518880 黄金ETF、513100 纳指ETF）
    - 1 开头：深市 ETF/基金（如 159941 纳指ETF）
    """
    if code.startswith(("6", "9", "5")):
        return "sh" + code
    if code.startswith(("0", "3", "1")):
        return "sz" + code
    if code.startswith(("8", "4")):
        return "bj" + code
    return "sh" + code


class AkshareFetcher(DataFetcher):
    """akshare 免费数据源。"""

    def fetch_daily_bars(self, code: str, start: str, end: str, with_adj_factor: bool = True) -> pd.DataFrame:
        """单只 A 股日线。返回「不复权价 + 复权因子 adj_factor」（正确性优先）。

        adj_factor = 后复权价 / 不复权价，回测时用 cleaner.adjust_price 按需复权，
        口径显式传入，杜绝「直接采前复权价导致除权日历史价被整体重算」的口径错误。
        with_adj_factor=False 时仅返回不复权价（省一次 API 调用）。
        """
        symbol = to_sina_symbol(code)
        raw = _retry(lambda: ak.stock_zh_a_daily(symbol=symbol, start_date=start, end_date=end, adjust=""))
        if raw is None:
            return pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume", "adj_factor"])
        raw = raw[["date", "open", "high", "low", "close", "volume"]].copy()
        raw["date"] = pd.to_datetime(raw["date"])

        if with_adj_factor:
            time.sleep(1)  # 两次调用间隔，降低被限流概率
            hfq = _retry(lambda: ak.stock_zh_a_daily(symbol=symbol, start_date=start, end_date=end, adjust="hfq"))
            if hfq is None:
                # 降级：拿不到复权因子就置 1（等同于不复权），并提示
                print(f"[fetcher] 复权因子获取失败，{code} 按不复权处理（adj_factor=1）")
                raw["adj_factor"] = 1.0
                return raw.reset_index(drop=True)
            hfq = hfq[["date", "close"]].rename(columns={"close": "close_hfq"})
            hfq["date"] = pd.to_datetime(hfq["date"])
            merged = raw.merge(hfq, on="date", how="left")
            merged["adj_factor"] = merged["close_hfq"] / merged["close"]
            merged["adj_factor"] = merged["adj_factor"].fillna(1.0)
            merged = merged.drop(columns=["close_hfq"])
            return merged.reset_index(drop=True)

        raw["adj_factor"] = 1.0
        return raw.reset_index(drop=True)

    def fetch_etf_bars(self, code: str, start: str, end: str) -> pd.DataFrame:
        """ETF 日线（黄金 ETF 518880 / 纳指 ETF 513100、159941）。"""
        symbol = to_sina_symbol(code)
        df = ak.fund_etf_hist_sina(symbol=symbol)
        df = df[["date", "open", "high", "low", "close", "volume", "amount"]].copy()
        df["date"] = pd.to_datetime(df["date"])
        if start:
            df = df[df["date"] >= pd.to_datetime(start)]
        if end:
            df = df[df["date"] <= pd.to_datetime(end)]
        return df.reset_index(drop=True)

    def fetch_stock_list(self) -> pd.DataFrame:
        """全市场股票列表（存续 + 退市），消除幸存者偏差。

        注意：存续股接口依赖上/深/北交所官网，网络不稳时可能失败；失败会重试，
        仍失败则返回退市股部分（并打印提示），不抛异常。
        """
        frames: list[pd.DataFrame] = []

        # 存续股（带重试）
        alive = _retry(lambda: ak.stock_info_a_code_name())
        if alive is not None:
            alive = alive.rename(columns={"code": "code", "name": "name"})
            alive["exchange"] = alive["code"].map(_exchange_of)
            alive["status"] = "listed"
            alive["list_date"] = ""
            alive["delist_date"] = ""
            frames.append(alive[["code", "name", "exchange", "status", "list_date", "delist_date"]])
        else:
            print("[fetcher] 存续股列表获取失败，本次仅返回退市股（如可获取）")

        # 上交所退市股
        sh = _retry(lambda: ak.stock_info_sh_delist())
        if sh is not None:
            sh = sh.rename(columns={
                "公司代码": "code", "公司简称": "name",
                "上市日期": "list_date", "暂停上市日期": "delist_date",
            })
            sh["exchange"] = "SH"
            sh["status"] = "delisted"
            frames.append(sh[["code", "name", "exchange", "status", "list_date", "delist_date"]])

        # 深交所退市股（列名按需匹配，容错）
        sz = _retry(lambda: ak.stock_info_sz_delist())
        if sz is not None:
            col_map = {}
            for src, dst in (("证券代码", "code"), ("证券简称", "name"),
                             ("上市日期", "list_date"), ("终止上市日期", "delist_date")):
                if src in sz.columns:
                    col_map[src] = dst
            sz = sz.rename(columns=col_map)
            sz["exchange"] = "SZ"
            sz["status"] = "delisted"
            need = ["code", "name", "exchange", "status", "list_date", "delist_date"]
            for c in ("list_date", "delist_date"):
                if c not in sz.columns:
                    sz[c] = ""
            frames.append(sz[need])

        if not frames:
            return pd.DataFrame(columns=["code", "name", "exchange", "status", "list_date", "delist_date"])

        out = pd.concat(frames, ignore_index=True)
        out["code"] = out["code"].astype(str).str.zfill(6)
        out["board"] = out["code"].map(_board_of)   # 板块（决定涨跌停幅度）
        out["is_st"] = out["name"].map(_is_st)       # 是否 ST
        return out.drop_duplicates(subset="code", keep="first").reset_index(drop=True)

    def fetch_trade_calendar(self, start: str, end: str) -> pd.DataFrame:
        """交易日历。"""
        cal = ak.tool_trade_date_hist_sina()
        cal = cal.rename(columns={"trade_date": "date"})
        cal["date"] = pd.to_datetime(cal["date"])
        cal["is_open"] = 1
        if start:
            cal = cal[cal["date"] >= pd.to_datetime(start)]
        if end:
            cal = cal[cal["date"] <= pd.to_datetime(end)]
        return cal[["date", "is_open"]].reset_index(drop=True)

    def fetch_fundamentals(self, code: str) -> pd.DataFrame:
        """基本面数据（同花顺财务摘要，质量因子所需）。

        返回列（英文标准名）：period / roe / gross_margin / net_margin /
        revenue_yoy / profit_yoy / debt_ratio / eps / bvps。
        数据为年度口径，报告期列标注数据截止年份（财报滞后性见 §4.1）。
        """
        df = _retry(lambda: ak.stock_financial_abstract_ths(symbol=code, indicator="按年度"))
        if df is None or df.empty:
            return pd.DataFrame()
        rename = {
            "报告期": "period",
            "净资产收益率": "roe",
            "销售毛利率": "gross_margin",
            "销售净利率": "net_margin",
            "营业总收入同比增长率": "revenue_yoy",
            "净利润同比增长率": "profit_yoy",
            "资产负债率": "debt_ratio",
            "基本每股收益": "eps",
            "每股净资产": "bvps",
        }
        df = df.rename(columns={k: v for k, v in rename.items() if k in df.columns})
        cols = [v for v in rename.values() if v in df.columns]
        return df[cols].reset_index(drop=True)


def _exchange_of(code: str) -> str:
    if code.startswith(("6", "9", "5")):
        return "SH"
    if code.startswith(("0", "3", "1")):
        return "SZ"
    return "BJ"


def _board_of(code: str) -> str:
    """由代码判断板块（决定涨跌停幅度）。"""
    if code.startswith("30"):
        return "gem"      # 创业板 20%
    if code.startswith("68"):
        return "star"     # 科创板 20%
    if code.startswith(("8", "4", "92")):
        return "bj"       # 北交所 30%
    return "main"         # 主板 10%


def _is_st(name: str) -> bool:
    """名称含 ST/*ST 视为风险警示股。"""
    return "ST" in str(name).upper()


def get_limit_rate(board: str, is_st: bool) -> float:
    """涨跌停幅度：ST 5%、创业板/科创板 20%、北交所 30%、主板 10%。"""
    if is_st:
        return 0.05
    if board in ("gem", "star"):
        return 0.20
    if board == "bj":
        return 0.30
    return 0.10
