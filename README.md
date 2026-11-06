# 量化交易系统（quant-system）

跨资产对冲配置量化系统（A 股多因子选股 + 黄金 ETF + 纳指 ETF，日频，SuperMind 模拟盘），含金融知识板块（RSS 聚合 + LLM 中文摘要 + 全文检索）。

> 详细需求见《量化交易系统开发需求文档.md》，本项目是它的完整实现。
> **全部 7 个里程碑（M1–M7）已交付，58 个单元测试全部通过。**

## 一、系统总览

```
quant-system/
├── main.py                    # CLI 入口（12 个子命令）
├── config/config.yaml         # 全局配置（成本/风控阈值/λ档位）
├── core/                      # 配置加载/日志
├── data/                      # 采集(akshare)/清洗/存储(SQLite+Parquet)
├── factors/                   # 因子引擎/内置因子库/中性化/质检
├── strategy/                  # 策略基类/跨资产对冲配置/双均线示例
├── backtest/                  # 事件驱动回测/撮合/绩效/Walk-Forward优化
├── execution/                 # BrokerAdapter/PaperBroker/SuperMindBroker
├── risk/                      # 三层风控/压力测试/相关性监控
├── report/                    # Markdown报告/matplotlib图表
├── web/                       # Streamlit 看板（量化+知识双板块）
├── knowledge/                 # RSS采集/LLM翻译/FTS5检索
└── tests/                     # 58 个单元测试
```

## 二、快速开始

```bash
cd quant-system
pip install -r requirements.txt

# 1. 采集数据
python main.py fetch-list                                          # 股票列表(含退市)+交易日历
python main.py fetch-etf --code 518880 --start 20150101            # 黄金ETF
python main.py fetch-etf --code 513100 --start 20150101           # 纳指ETF
python main.py fetch-batch --codes 600519,000858,601318 --start 20200101  # 批量股票

# 2. 回测
python main.py backtest --strategy dual_ma --codes 600519          # 双均线(验证链路)
python main.py backtest --strategy cross_asset --top-n 5           # 跨资产对冲配置(核心)

# 3. 分析与监控
python main.py factors-qa                                          # 因子质检(IC/分层/去相关)
python main.py stress                                             # 压力测试(历史情景回放)
python main.py monitor                                            # 相关性监控(分散失效)

# 4. 模拟盘(需 SuperMind 客户端；缺 SDK 时自动 DryRun)
python main.py run-paper

# 5. 知识板块
python main.py fetch-news [--translate]                           # RSS 采集(+LLM中文摘要)

# 6. Web 看板
streamlit run web/app.py                                          # http://localhost:8501

# 7. 测试
python -m pytest tests/ -q                                        # 58 passed
```

## 三、核心策略：跨资产对冲配置

**定位**：用低相关资产（黄金、纳指）对 A 股系统性风险做分散/对冲（非 Beta 中性，不做期货）。

- **A 股多因子选股**（Alpha 端）：动量(20/60/120d) + 波动率(逆向) + 5日反转，截面 z-score 等权合成 → top N
- **黄金 ETF 518880**（避险端）：与 A 股长期近零相关（实证 0.071）
- **纳指 ETF 513100**（分散端）：低正相关（0.235），但危机时相关性飙升（2020 疫情 0.69）——是分散而非对冲

**风险档位 λ（并轨机制）**：

```
最终权重 = 固定基准权重(6:2:2) × (1 − λ) + 动态择时权重 × λ
动态择时 = 风险平价(1/σ) + 动量调整，裁剪到单资产 [10%, 70%]
```

| 档位 | λ | 说明 |
|---|---|---|
| 稳健 | 0.1 | 权重近锁定固定比例，靠再平衡 |
| 平衡 | 0.5 | 一半固定、一半跟随择时（默认） |
| 进取 | 0.9 | 主要跟随择时信号大幅调仓 |

再平衡：每月末检查，任一资产偏离 >5% 触发，只调超出阈值部分（控换手成本）。

## 四、风控（三层，独立于策略强制执行）

- **事前**：单标的/单笔上限、资金校验、价格偏离拦截（乌龙指防护）→ 不过直接拒绝
- **事中**：敞口监控、单日订单频率拦截
- **事后**：回撤复盘、事件 append-only 留痕
- **压力测试**：2015 股灾/2018 贸易战/2020 疫情/2024 微盘股危机情景回放 + 对冲失效测试（三资产危机相关性突变检测）

## 五、开发红线（实现已全部遵守）

1. **无未来函数**：信号 T 日收盘产生，T+1 开盘成交（引擎级保证，测试覆盖）
2. **无幸存者偏差**：股票列表含退市股
3. **复权口径显式**：存不复权价 + adj_factor，按需 qfq/hfq
4. **停牌/涨跌停不可成交**：一字板跳过
5. **成本必计入**：佣金(万2.5,最低5元) + 印花税(卖0.05%) + 过户费 + 滑点
6. **T+1**：当日买入次日解锁
7. **回测/模拟盘共用策略代码**：同一 Strategy，仅 Broker 不同
8. **参数优化 Walk-Forward**：训练/测试分离 + 邻域稳健性
9. **数据不得编造**：取不到报「未覆盖」
10. **风控独立**：BrokerAdapter 之前强制校验

## 六、SuperMind 模拟盘接入（用户侧步骤）

1. 下载 SuperMind 体验版（官方 quant.10jqka.com.cn）
2. 同花顺账号登录客户端
3. 客户端内添加「仿真模拟账号」
4. 设置环境变量 `SUPERMIND_ACCOUNT=模拟资金账号`，保持客户端登录
5. SDK 未装时系统自动 DryRun（订单入本地库不发真实委托）

## 七、知识板块

- RSS 免费源聚合（`knowledge/sources.yaml` 可增删）
- LLM 中文翻译+摘要（环境变量 `ZHIPU_API_KEY`，未配置自动跳过）
- SQLite FTS5 全文检索（中英文标题/摘要）
- Web 看板「知识库」页检索浏览

## 八、关键约定

- 标的代码：A 股 6 位（`600519`）；黄金 `518880`；纳指 `513100`/`159941`
- 日频，年化 252；默认基准权重 6:2:2；λ 默认 0.5
- 策略跨档位回测：`python main.py backtest --strategy cross_asset --lam 0.1/0.5/0.9`
