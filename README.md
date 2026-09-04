# crypto-trading-agents

一个面向加密货币的多智能体研究框架，参考了
[TauricResearch/TradingAgents](https://github.com/TauricResearch/TradingAgents)
的分析师、研究员、风险和组合管理编排方式，但把数据源改成了币安公开现货行情、
Fear & Greed Index、RSS 新闻，以及可选的 OKX 合约与账户数据。

这个项目默认不做交易执行，只输出结构化研究报告和风险控制建议。

## 架构

```text
Binance Spot / Fear & Greed / RSS
        |
Market Data Agent
        |
Technical / Derivatives / Sentiment / News
        |
Bull Researcher  <-  Bear Researcher
        |
Risk Manager
        |
Portfolio Manager
```

默认流程完全离线可推理，不依赖任何 LLM。可选地配置一个 OpenAI-compatible endpoint，
让 Portfolio Manager 在最后生成更自然的中文结论；未配置时会使用规则引擎生成结论。

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

复制 `.env.example` 后按需填写。行情接口默认不需要密钥；如果要用私有账户信息，可以把
`OKX_CONFIG_PATH` 指向现有的 OKX 配置文件，或者在 `.env` 中填写密钥。

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

报告会写入 `reports/<instrument>/<timestamp>.md` 和同名 JSON 文件。

## Agent 分工

- **Market Data Agent**：从币安公开接口汇总 ticker、K 线、盘口深度和订单簿不平衡。
- **Technical Agent**：计算 EMA、RSI、MACD、ATR、Bollinger Bands、成交量异常。
- **Derivatives Agent**：可选读取 OKX 永续合约资金费率、持仓量和订单簿压力。
- **Derivatives Agent 数据口径说明**：资金费率与持仓量来自 OKX 合约市场，
  与币安现货价格存在口径差异，仅供参考。
- **Sentiment Agent**：读取 Fear & Greed Index，并给出情绪区间。
- **News Agent**：抓取 CoinDesk / Cointelegraph RSS 的最新标题，做轻量关键词打分。
- **Bull / Bear Researcher**：分别构建多头与空头论据，并给出强度评分。
- **Risk Manager**：基于 ATR 计算建议止损距离和单笔风险仓位。
- **Portfolio Manager**：把以上报告合成 `BUY / HOLD / SELL` 与置信度。

## Cycle of Price Action

`crypto_trading_agents.cycle` 提供了一个更接近 Oliver Kell 原始框架的阶段化
量化版本。它不会把主观形态完全机械化，而是把周期拆成：

- `reversal_extension`
- `wedge_pop`
- `ema_crossback`
- `base_n_break`
- `exhaustion_extension`
- `wedge_drop`
- `ema_crossback_downside`
- `base_n_break_downside`

它同时输出可量化的形态标签：

- `capitulation_reversal`
- `flat_base_breakout`
- `bull_flag_breakout`
- `double_bottom_breakout`
- `higher_low_reclaim`

多周期结构由三层组成：

- **Weekly**：周线 EMA20/50 趋势
- **Daily**：日线 EMA10/EMA20/SMA50/SMA200 趋势和 HH/HL、LH/LL 结构
- **4H（可选）**：4 小时趋势与回踩确认，仅作为辅助执行周期，不再强制入场

模型还会计算 ETH 对 BTC 的 20 日相对强弱，并在入场评分中使用；回测 BTC 时会
自动改用 ETH 作为相对强弱基准。

模型还包含三块核心结构：

- **周期状态机**：把价格行为推进为 `accumulation → recovery → markup → distribution → markdown`，
  并记录状态转换、状态持续时间和阶段顺序是否有效。
- **摆动结构引擎**：识别已确认的 swing high / swing low，计算 HH/HL、LH/LL、
  结构得分和结构质量。
- **形态质量评分**：按形态紧凑度、量能、趋势、周期状态、摆动结构和触发确认
  等维度给 0-100 分，输出 A/B/C/D/F 等级。
- **阶段化交易管理**：底部反转用更小仓位和更紧止损，趋势延续阶段逐步放大仓位，
  衰竭阶段可按需部分止盈。仓位还受单笔风险、质量评分和最大仓位约束。
- **回测成本与风控**：支持滑点、永续资金费率、杠杆、维持保证金率和强平检查。

回测脚本：

```bash
python scripts/backtest_cycle_full.py
```

信号在 T 日收盘确认；回测里用 T+1 日线开盘价近似执行，避免使用收盘前不可知的数据。

### 回测参数默认值

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--execution-mode` | `daily` | `4h` 模式下入场额外要求当日 4H 出现回踩反弹确认 |
| `--symbol` | `ETHUSDT` | 回测标的 |
| `--start` / `--end` | 近一年 | 回测区间 |
| `--fee` | `0.001` (0.1%) | 双边手续费 |
| `--stop-atr` | `2.0` | 止损 ATR 倍数 |
| `--trail-atr` | `3.0` | 移动止损 ATR 倍数 |
| `--partial-exit` | `0.0`（关） | 衰竭阶段部分止盈比例 |
| `--swing-window` | `3` | 摆动点确认窗口 |
| `--min-quality` | `40.0` | 形态质量门槛 |
| `--min-setup-score` | `60.0` | 入场评分门槛 |
| `--risk-per-trade` | `0.03` (3%) | 单笔风险 |
| `--slippage` | `0.0005` (0.05%) | 滑点 |
| `--funding-rate-annual` | `0.10` (10%) | 资金费率年化 |
| `--leverage` | `1.0` | 杠杆 |
| `--maintenance-margin` | `0.005` | 维持保证金率 |
| `--benchmark-symbol` | `BTCUSDT` | 相对强弱基准（BTC 回测自动切换为 ETH） |

### 4H 执行模式

`--execution-mode 4h` 不会改变信号确认时点（仍是日线收盘），而是在入场条件中
额外要求当日至少一根 4H K 线出现回踩反弹结构（价格触及 4H EMA20 后收回且收盘
高于开盘）。成交仍以 T+1 日线开盘价近似。

### Walk-forward 配置

使用 `--walk-forward` 开启滚动样本外验证：

- 训练窗口：180 天（`--train-days`）
- 测试窗口：90 天（`--test-days`）
- 阈值网格：`min_setup_score ∈ {50, 60, 70}`
- 训练集选择标准：最大化 `策略收益 - 0.5 × |最大回撤|`
- 测试窗口按 90 天步进，逐折输出样本外收益

### 优化模块

详细的原文整理、阶段说明、图表索引和本地示意图见
[`docs/cycle-of-price-action/README.md`](docs/cycle-of-price-action/README.md)。

## 优化模块

- `crypto_trading_agents/metrics.py`：Sharpe、Sortino、Calmar、回撤、连续亏损和盈亏比。
- `crypto_trading_agents/exit_manager.py`：结构破位、均线出场、时间止损和阶梯移动止损。
- `crypto_trading_agents/entry_manager.py`：A/B/C 分层入场与建议仓位。
- `crypto_trading_agents/multi_timeframe.py`：日线准备信号 + 4H 战术触发。
- `crypto_trading_agents/adaptive_exit.py`：波动率/趋势状态驱动的自适应出场。
- `crypto_trading_agents/monte_carlo.py`：交易序列蒙特卡洛和参数敏感性分析。
- `crypto_trading_agents/trend_base.py`：趋势底仓与周期加仓。
- `crypto_trading_agents/sentiment_filter.py`：Fear & Greed 和资金费率情绪过滤。
- `crypto_trading_agents/portfolio_risk.py`：组合回撤控制、分批建仓与滑点模型。

其中 P4-P6 模块目前是独立组件，尚未接入主回测。当前优先使用 `daily` 模式和
2020 年起的 BTC / ETH 数据做基线验证。

### 当前策略状态 (v0.9)

BTC 使用「15% 趋势底仓 + 85% 信号层」组合路径，信号层启用
`use_btc_exit_final`（盈利仓用动态结构出场）。ETH V3 为纯底仓模式（20%），
普通信号禁用，仅保留 85/85 极端例外。两种资产均已接入成本管道（手续费 +
滑点 + 资金费率）。

关键结果：

| 指标 | BTC | ETH V3 |
|------|-----|--------|
| 总收益 | `+100.23%` | `+61.39%` |
| Sharpe | `1.028` | `0.701` |
| 最大回撤 | `-12.81%` | `-15.49%` |
| WF 正收益 | `9/28` | `11/28` |

滑点敏感性：BTC 在 0.2% 滑点时 Sharpe 降至 0.943；ETH V3 交易频率低，
滑点影响可忽略。

最终决策脚本（含蒙特卡洛和 Go/No-Go）：

```bash
python scripts/final_decision.py
```

滑点敏感性分析：

```bash
python scripts/slippage_sensitivity.py
```

模拟盘 runner（每天日线收盘后跑一次）：

```bash
python scripts/paper_trading.py
```

模拟盘状态写入 `paper_trading/state.json`，交易日志追加到
`paper_trading/trades.jsonl`。数据源为币安公开 API，内地可直连。

`data/BTC_1d.csv` 和 `data/ETH_1d.csv` 已扩展为 `2020-01-01` 到 `2026-09-04`
的日线快照，用于扩大样本量。

数据校验：

```bash
python scripts/validate_data.py --data-dir data --symbols BTCUSDT ETHUSDT
```

集成示例：

```bash
python scripts/backtest_with_optimizations.py --symbol ETHUSDT
```

策略诊断：

```bash
python scripts/trade_review.py --symbol BTCUSDT --data-file data/BTC_1d.csv
python scripts/exposure_analysis.py --symbol ETHUSDT --data-file data/ETH_1d.csv
python scripts/param_stability_check.py --symbol BTCUSDT --data-file data/BTC_1d.csv
```

修复项验证：

```bash
python scripts/backtest_with_fixes.py --symbol BTCUSDT --data-file data/BTC_1d.csv --use-exit-optimizer --use-trend-base
python scripts/backtest_with_fixes.py --symbol ETHUSDT --data-file data/ETH_1d.csv --use-exit-optimizer --use-eth-fix --use-trend-base
```

Walk-forward 与归因：

```bash
python scripts/walk_forward_with_fixes.py --symbols BTCUSDT ETHUSDT
python scripts/attribution_analysis.py --symbol BTCUSDT
python scripts/attribution_analysis.py --symbol ETHUSDT --use-eth-exit-v2
```

## 免责声明

项目仅供研究和学习，不构成投资建议。加密资产波动性极高，使用任何建议前请自行验证数据、
模型和风控参数。
