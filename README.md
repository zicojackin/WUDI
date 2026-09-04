# crypto-trading-agents

加密货币多智能体研究框架。编排方式参考 [TauricResearch/TradingAgents](https://github.com/TauricResearch/TradingAgents)，数据源替换为币安现货公开行情、Fear & Greed Index 和 RSS 新闻，可选接入 OKX 合约与账户数据。

**本项目只输出研究报告与模拟交易信号，不执行任何真实交易。**

## 当前状态：v0.9-frozen（策略冻结期）

策略逻辑已冻结，正在进行 60 天模拟盘（paper trading）验证，预期于 2026-11 初结束。冻结期内：

- 不修策略逻辑、不调参数；只修数据正确性 bug（如已修复的未收盘 K 线污染）
- 模拟盘定位是**管道验证**（无 repaint、状态按收盘推进、填充价偏差），不是策略边缘验证
- 成功标准已预登记，见 [HANDOFF.md](HANDOFF.md)

关键文档：

| 文档 | 内容 |
|------|------|
| [HANDOFF.md](HANDOFF.md) | 回测结果、口径说明、Go/No-Go 标准、模拟盘成功标准 |
| [DEFERRED.md](DEFERRED.md) | 延期优化事项，每条带启动条件 |
| [docs/cycle-of-price-action/README.md](docs/cycle-of-price-action/README.md) | Cycle 模型原文整理、阶段说明、图表索引 |

## 架构

```
数据源（Binance 现货 / Fear & Greed / RSS / OKX 可选）
        |
        v
Market Data Agent                              <- 数据汇总
        |
        v
Technical / Derivatives / Sentiment / News     <- 并行分析
        |
        v
Bull Researcher <-> Bear Researcher            <- 多空辩论
        |
        v
Risk Manager                                   <- 风控
        |
        v
Portfolio Manager                              <- 合成 BUY / HOLD / SELL 与置信度
```

## Agent 分工

| Agent | 职责 |
|-------|------|
| Market Data Agent | 从币安公开接口汇总 ticker、K 线、盘口深度和订单簿不平衡 |
| Technical Agent | 计算 EMA、RSI、MACD、ATR、Bollinger Bands、成交量异常 |
| Derivatives Agent | 可选读取 OKX 永续合约资金费率、持仓量和订单簿压力（**数据来自 OKX，与币安现货存在口径差异**） |
| Sentiment Agent | 读取 Fear & Greed Index，并给出情绪区间 |
| News Agent | 抓取 CoinDesk / Cointelegraph RSS 最新标题，做轻量关键词打分 |
| Bull / Bear Researcher | 分别构建多头与空头论据，并给出强度评分 |
| Risk Manager | 基于 ATR 计算建议止损距离和单笔风险仓位 |
| Portfolio Manager | 把以上报告合成 `BUY / HOLD / SELL` 与置信度 |

## 安装

```bash
cd crypto-trading-agents
python -m venv .venv

# Windows
.venv\Scripts\activate

# macOS / Linux
source .venv/bin/activate

pip install -e .
```

复制 `.env.example` 为 `.env` 后按需填写。行情接口默认不需要密钥；如需读取私有账户信息，可将 `OKX_CONFIG_PATH` 指向现有的 OKX 配置文件，或在 `.env` 中填写密钥。

## 使用

分析 ETH 现货：

```bash
crypto-agents analyze ETH-USDT --bar 4H --limit 200
```

分析 BTC 永续合约，并读取资金费率和持仓量：

```bash
crypto-agents analyze BTC-USDT --swap
```

同时读取私有账户余额和持仓：

```bash
crypto-agents analyze ETH-USDT --swap --account
```

只看原始行情：

```bash
crypto-agents data BTC-USDT --bar 1H --limit 30
```

分析报告写入 `reports/<instrument>/<timestamp>.md` 和同名 JSON 文件。

## Cycle of Price Action 策略

内置基于 Oliver Kell "Cycle of Price Action" 的阶段化量化模型，当前为 **long-only** 设计：空头阶段只用于持仓出场判断，不做裸空。

### 周期阶段

8 个阶段按多空方向对称推进：

| 方向 | 阶段推进 |
|------|----------|
| 多头（可开仓） | `reversal_extension` -> `wedge_pop` -> `ema_crossback` -> `base_n_break` |
| 空头（仅用于出场） | `exhaustion_extension` -> `wedge_drop` -> `ema_crossback_downside` -> `base_n_break_downside` |

另附带形态标签用于入场质量评分，完整列表见 cycle 模块源码。

### 三层周期结构

模型在 Weekly / Daily / 4H 三个层级分别运行：上层周期决定方向偏好，下层周期负责入场确认。同时计算标的相对 BTC 的强弱评分；当回测标的为 BTC 时，自动改用 ETH 作为基准。

### 核心结构

模型包含三层核心结构：

**1. 状态识别层**

- **周期状态机**：把价格行为推进为 `accumulation -> recovery -> markup -> distribution -> markdown`，记录状态转换、状态持续时间和阶段顺序是否有效
- **摆动结构引擎**：识别已确认的 swing high / swing low，计算 HH/HL、LH/LL、结构得分和结构质量

**2. 评分层**

- **形态质量评分**：按形态紧凑度、量能、趋势、周期状态、摆动结构和触发确认等维度给出 0-100 分，输出 A / B / C / D / F 等级

**3. 执行与风控层**

- **阶段化交易管理**：底部反转用更小仓位和更紧止损，趋势延续阶段逐步放大仓位，衰竭阶段可按需部分止盈；仓位还受单笔风险、质量评分和最大仓位约束
- **回测成本与风控**：支持滑点、永续资金费率、杠杆、维持保证金率和强平检查

## 回测与模拟盘

主组合为 **BTC 完整 cycle 模型**（含 trend_base 底仓与 partial exit）；ETH 侧运行独立的保守变体（底仓 + 极端信号加仓）。当前结果与全部指标口径见 [HANDOFF.md](HANDOFF.md)。

### 回测

```bash
python scripts/backtest_cycle_full.py
```

默认假设：双边 0.1% 手续费、ATR 止损 + 移动止损。信号在 T 日收盘确认，以 T+1 开盘价近似执行，避免使用收盘前不可知的数据（前视偏差）。K 线数据经过未收盘 bar 过滤，回测与模拟盘共用同一条数据管道。

| 参数 | 说明 |
|------|------|
| `--execution-mode` | `daily`（默认）/ `4h`（重新启用 4H 回踩确认） |
| `--partial-exit` | 衰竭阶段部分止盈 |
| `--full` | 输出完整净值曲线 |
| `--min-quality` | 形态质量门槛 |
| `--swing-window` | 摆动点确认窗口 |
| `--walk-forward` | 滚动选择入场评分阈值，输出样本外结果 |
| `--slippage` | 滑点假设 |
| `--funding-rate-annual` | 永续资金费率（年化） |
| `--leverage` | 杠杆倍数 |
| `--maintenance-margin` | 维持保证金率 |

默认值见 `python scripts/backtest_cycle_full.py --help`。

### 模拟盘（当前生产入口）

```bash
python scripts/paper_trading.py
```

每日收盘后运行，输出 `daily_state` 与交易事件到 `trades.jsonl`（schema 说明见 HANDOFF.md），状态持久化于 `state.json`。

## 免责声明

本项目仅供研究和学习，不构成投资建议。加密资产波动性极高，使用任何建议前请自行验证数据、模型和风控参数。
