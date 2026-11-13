"""i18n 双语模块（中/英切换）。

用法：
    from web.i18n import lang_selector, t
    lang_selector()               # 右上角单按钮循环切换（app.py 全局渲染一次）
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
    "绩效分析": "Performance Analysis",
    "净值对比基准": "Equity vs Benchmark",
    "月度收益热力图": "Monthly Returns Heatmap",
    "日收益分布": "Daily Return Distribution",
    "收益与风险总览": "Return & Risk Overview",
    "个交易日": "trading days",
    "索提诺比率": "Sortino",
    "卡玛比率": "Calmar",
    "月度胜率": "Monthly Win Rate",
    "基准": "Benchmark",
    "基准收益": "Benchmark Return",
    "超额收益": "Excess Return",
    "信息比率": "Information Ratio",
    "对齐中…": "Aligning…",
    "策略净值": "Strategy NAV",
    "超额": "Excess",
    "归一化口径说明": "Both curves normalized to 1.0 at the first overlapping date",
    "基准重叠不足": "Insufficient overlap with benchmark",
    "回撤曲线": "Drawdown Curve",
    "尾部风险": "Tail Risk",
    "日损失超过此值的概率为 5%": "Daily loss exceeds this with 5% probability",
    "最坏 5% 日均损失": "Mean loss of worst 5% days",
    "日损失超过此值的概率为 1%": "Daily loss exceeds this with 1% probability",
    "最坏 1% 日均损失": "Mean loss of worst 1% days",
    "正态参考": "Normal Reference",
    "区间": "Bin",
    "天数": "Days",
    "偏度": "Skewness",
    "超额峰度": "Excess Kurtosis",
    "尖峰厚尾提示": "fat tails vs normal",
    "数据区间": "Data Range",
    "基准源": "Benchmark Source",
    "缓存": "Cache",
    "个股K线": "Stock Chart",
    "买卖点标注": "Trade Markers",
    "最新价": "Last Price",
    "近1年涨跌": "1Y Change",
    "52周最高": "52W High",
    "52周最低": "52W Low",
    "资产权重分布": "Asset Weight Allocation",
    "现金": "Cash",
    "日收益": "Daily Return",
    "时间窗口": "Time Window",
    "全部": "All",
    "后复权": "Adjusted (hfq)",
    "不足一年": "< 1Y of data",
    "我方成交明细": "My Trade Blotter",
    "笔": "trades",
    "可用现金": "Available Cash",
    "账户余额": "Account Balance",
    "原始价": "Raw Price",
    "复权价": "Adjusted Price",
    "首页仪表盘": "Dashboard",
    "系统控制台": "System Console",
    "回测报告": "Backtest Report",
    "因子质检": "Factor QA",
    "风控中心": "Risk Control",
    "知识库": "Knowledge Base",
    "运行中心": "Run Center",
    "金融工作台": "Financial Workbench",
    "跨资产对冲配置": "Cross-Asset Hedge",
    "年区间": "-yr span",
    "复利口径": "Compounded",
    "水下曲线见下": "see underwater below",
    "日频年化": "Daily Ann.",
    "暂无回测结果。运行 python main.py backtest --strategy cross_asset 生成。": "No backtest yet. Run python main.py backtest --strategy cross_asset.",
    "研究/模拟用途，不构成投资建议。": "For research/paper trading only. Not investment advice.",
    "系统操作台 · 数据采集 / 回测 / 因子 / 风控 / 执行 · 后台运行 + 实时日志": "Console · Data / Backtest / Factors / Risk / Execution · Background + Live Logs",
    "净值 · 回撤 · 月度热力 · λ 三档对比 · 资产K线": "Equity · Drawdown · Monthly Heatmap · λ Dials · Asset Candles",
    "持仓 · 订单 · 成交流水 · A股 + ETF": "Positions · Orders · Trades · A-Share + ETF",
    "持仓": "Positions",
    "知识库": "Knowledge Base",
    "自起始日全部": "All Since Start",
    "近30天": "Last 30d",
    "近7天": "Last 7d",
    "今日": "Today",
    "委托笔数": "# Orders",
    "正式运行": "Live Days",
    "天": "days",
    "起": "onward",
    "模拟盘正式运行自": "Paper trading since",
    "此前调试单不计入": "debug orders excluded",
    "秒自动刷新": "s auto-refresh",
    "回测重放": "Backtest Replay",
    "实盘拟合": "Paper Live",
    "净值视图": "NAV View",
    "数据积累中，指标需 ≥10 天后稳定": "accumulating data; metrics stable after ≥10 days",
    "样本不足30天": "<30d sample",
}


def lang_selector(where: str = "top") -> str:
    """渲染语言切换器（右上角单按钮，点击在 中/EN 间循环切换）。

    返回当前语言 'zh'/'en'。where 参数保留向后兼容：
    - "top"（默认）：主内容区右上角单按钮
    - "sidebar"：侧栏右上角单按钮
    """
    cur = st.session_state.get("lang", "zh")
    nxt = "en" if cur == "zh" else "zh"
    # 按钮文案显示「将要切换到的语言」：中文界面显示 EN，英文界面显示 中文
    label = "🌐 EN" if cur == "zh" else "🌐 中文"
    if where == "sidebar":
        holder = st.sidebar
        if holder.button(label, key="lang_toggle_sb", use_container_width=True):
            st.session_state["lang"] = nxt
            st.rerun()
    else:
        # 单列布局把按钮推到最右侧（视觉右上角）
        holder = st.columns([1, 0.11])[1]
        with holder:
            if st.button(label, key="lang_toggle", use_container_width=True):
                st.session_state["lang"] = nxt
                st.rerun()
    return st.session_state.get("lang", "zh")


def t(zh: str) -> str:
    """取当前语言文案。zh 键不存在英文映射时原样返回（中文兜底）。"""
    if st.session_state.get("lang", "zh") == "en":
        return _EN.get(zh, zh)
    return zh
