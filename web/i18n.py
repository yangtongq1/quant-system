"""i18n 双语模块（中/英切换）。

用法：
    from web.i18n import lang_selector, t
    lang_selector()               # 侧栏顶部渲染语言切换器
    st.markdown(t("持仓概览"))     # 取当前语言文案（中文键 → 中/英文值）
"""
from __future__ import annotations

import streamlit as st

# 中文键 → 英文值（中文即默认文案；t(键) 在 EN 模式返回英文）
_EN: dict[str, str] = {
    "QUANT TERMINAL": "QUANT TERMINAL",
    "金融工作台": "Financial Workbench",
    "系统状态": "System Status",
    "本地行情标的": "Local Symbols",
    "数据库": "Database",
    "已初始化": "Ready",
    "未初始化": "Not Init",
    "回测报告": "Backtest Reports",
    "核心策略": "Core Strategy",
    "跨资产对冲": "Cross-Asset Hedge",
    "持仓概览": "Holdings Overview",
    "持仓明细": "Positions Detail",
    "持仓总数": "Total Positions",
    "持股数": "Volume",
    "名称": "Name",
    "代码": "Code",
    "成本价": "Avg Cost",
    "最新价": "Last Price",
    "市值": "Market Value",
    "权重": "Weight",
    "类别": "Type",
    "板块": "Board",
    "行业": "Industry",
    "方向": "Side",
    "买入": "Buy",
    "卖出": "Sell",
    "价格": "Price",
    "数量": "Volume",
    "金额": "Amount",
    "费用": "Fee",
    "时间": "Time",
    "状态": "Status",
    "已委托": "Submitted",
    "风控拒绝": "Rejected",
    "已成交": "Filled",
    "废单": "Dead",
    "部成": "Partially Filled",
    "订单": "Orders",
    "成交流水": "Trade Blotter",
    "交割单": "Settlement Statement",
    "交易日报": "Daily Report",
    "一键操作台": "One-Click Console",
    "行情与舆情": "Market & Sentiment",
    "控制台": "Console",
    "回测": "Backtest",
    "因子": "Factors",
    "风控": "Risk",
    "知识库": "Knowledge",
    "运行记录": "Runs",
    "持仓与订单": "Positions & Orders",
    "一键拉取最新K线": "Fetch Latest K-Lines",
    "盈亏分析": "P&L Analysis",
    "交易日涨跌幅": "Daily Change",
    "持仓体检": "Position Health Check",
    "数据健康检查": "Data Health Check",
    "运行中…": "Running…",
    "完成": "Done",
    "暂无数据": "No data yet",
    "语言": "Language",
    "生成日报": "Generate Daily Report",
    "当日成交": "Today's Trades",
    "成交笔数": "# Trades",
    "成交金额": "Turnover",
    "买入金额": "Buy Amount",
    "卖出金额": "Sell Amount",
    "持仓盈亏": "Position P&L",
    "风控事件": "Risk Events",
    "快讯": "Flash News",
    "市场情绪": "Market Sentiment",
    "涨跌家数": "Adv/Dec Count",
    "指数行情": "Index Quotes",
    "自选股行情": "Watchlist Quotes",
    "刷新": "Refresh",
    "报告已生成": "Report Generated",
    "A股仓位市值": "A-Share MV",
    "ETF 仓位市值": "ETF MV",
    "合计市值": "Total MV",
    "按最新收盘价": "At Last Close",
    "黄金+纳指": "Gold + Nasdaq",
    "最新收盘价口径": "At Last Close",
    "收益率": "Return",
    "累计收益": "Total Return",
    "年化收益": "Ann. Return",
    "最大回撤": "Max Drawdown",
    "夏普比率": "Sharpe",
    "年化波动": "Ann. Vol",
    "净值曲线": "Equity Curve",
    "水下曲线": "Underwater Curve",
    "最新回测": "Last Backtest",
    "报告": "Report",
    "策略": "Strategy",
    "日期": "Date",
    "备注": "Remark",
    "原因": "Reason",
    "操作": "Action",
    "点击上方按钮执行对应任务": "Click a button above to run the task",
}


def lang_selector(where: str = "sidebar") -> str:
    """渲染语言切换器（sidebar 或 main）。返回当前语言 'zh'/'en'。"""
    options = {"中文": "zh", "EN": "en"}
    labels = list(options)
    default = 0 if st.session_state.get("lang", "zh") == "zh" else 1
    holder = st.sidebar if where == "sidebar" else st
    pick = holder.selectbox("🌐 Language / 语言", labels, index=default,
                            label_visibility="collapsed")
    st.session_state["lang"] = options[pick]
    return st.session_state["lang"]


def t(zh: str) -> str:
    """取当前语言文案。zh 键不存在英文映射时原样返回（中文兜底）。"""
    if st.session_state.get("lang", "zh") == "en":
        return _EN.get(zh, zh)
    return zh
