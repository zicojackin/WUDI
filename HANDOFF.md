# Cycle of Price Action 转接摘要

- **版本：** v0.9
- **更新日期：** 2026-09-04
- **回测快照：** 基于 commit `330db01`（v0.8 首次提交）；v0.9 更新后复现入口为
  `python scripts/final_decision.py`。

## 当前目标

策略目标是 **BTC / ETH 上风险调整后的中长期多头收益**，优先关注 Sharpe / Sortino、
最大回撤、连续亏损和暴露调整后收益，而不是单纯和买入持有比绝对收益。

用户主要交易 **BTC 和 ETH**，偏好 **中长期、只做多** 的周期策略。当前项目是把 TraderLion
「Cycle of Price Action」模型改造成可回测的量化近似版本，不追求复刻原版的主观判断。

## 项目位置

`C:\Users\Admin\Documents\ChatGPT\1\crypto-trading-agents`

## 关键文件

- `crypto_trading_agents/cycle.py`：周期阶段、状态机、摆动结构、形态评分、回测引擎。
- `crypto_trading_agents/metrics.py`：风险调整回测指标。
- `crypto_trading_agents/exit_manager.py`：结构、均线、时间和阶梯移动止损模块。
- `crypto_trading_agents/entry_manager.py`：A/B/C 分层入场模块。
- `crypto_trading_agents/multi_timeframe.py`：P4 多时间框架入场引擎。
- `crypto_trading_agents/adaptive_exit.py`：P4 自适应出场模块。
- `crypto_trading_agents/monte_carlo.py`：P5 蒙特卡洛与参数敏感性模块。
- `crypto_trading_agents/trend_base.py`：P5 趋势底仓与周期加仓模块。
- `crypto_trading_agents/sentiment_filter.py`：P5 情绪/资金费率过滤模块。
- `crypto_trading_agents/portfolio_risk.py`：P6 组合回撤控制、分批建仓与滑点模型。
- `crypto_trading_agents/exit_optimizer.py`：出场优化器，阶梯跟踪 + 回调容忍。
- `crypto_trading_agents/trend_base_simple.py`：简化趋势底仓。
- `crypto_trading_agents/eth_fix.py`：ETH 低质量信号过滤。
- `crypto_trading_agents/btc_exit_final.py`：BTC 最终出场规则。
- `crypto_trading_agents/eth_strategy_v3.py`：ETH V3 纯底仓策略。
- `scripts/final_decision.py`：最终蒙特卡洛与 Go/No-Go 决策脚本。
- `scripts/slippage_sensitivity.py`：滑点敏感性分析。
- `.github/workflows/ci.yml`：GitHub Actions CI，push/PR 自动跑 pytest。
- `scripts/backtest_with_fixes.py`：修复项组合验证脚本。
- `scripts/walk_forward_with_fixes.py`：修复前后滚动样本外对比。
- `scripts/attribution_analysis.py`：分年度、Alpha/Beta 与市场阶段归因。
- `scripts/backtest_cycle_full.py`：BTC/ETH 回测与 walk-forward 脚本。
- `scripts/backtest_with_optimizations.py`：优化模块集成示例。
- `scripts/validate_data.py`：OHLCV 数据完整性校验。
- `scripts/trade_review.py`：逐笔交易复盘。
- `scripts/exposure_analysis.py`：暴露成本分析。
- `scripts/param_stability_check.py`：核心参数扰动测试。
- `data/BTC_1d.csv`、`data/ETH_1d.csv`：本地日线快照。
- `docs/cycle-of-price-action/README.md`：TraderLion 原始内容整理与图片索引。
- `README.md`：项目使用说明。
- `HANDOFF.md`：当前交接摘要。

## 模型现状

策略核心是周期状态机：

`accumulation → recovery → markup → distribution → markdown`

已实现：

- 8 个 Cycle 阶段：Reversal Extension、Wedge Pop、EMA Crossback、Base n' Break、
  Exhaustion Extension、Wedge Drop、EMA Crossback Downside、Base n' Break Downside。
- 可量化形态标签：`capitulation_reversal`、`flat_base_breakout`、
  `bull_flag_breakout`、`double_bottom_breakout`、`higher_low_reclaim`。
- 摆动结构引擎：swing high / swing low、HH/HL、LH/LL、结构得分。
- 形态质量评分：0-100，输出 A/B/C/D/F。
- 均线体系：EMA10、EMA20、SMA50、SMA200。
- ETH/BTC 相对强弱：ETH 回测基准是 BTC，BTC 回测基准是 ETH。
- 阶段化仓位与止损/移动止损。
- 滑点、资金费率、杠杆、维持保证金率与强平检查。
- `execution_mode`：
  - 默认 `daily`
  - 可选 `4h`
  - `4h` 不再是硬性门槛，只作为可选辅助执行周期。

## ETH 专属规则

ETH 使用独立 profile：

- 初始止损统一为 `2 x ATR`
- 移动止损统一为 `3 x ATR`
- 高质量 Reversal Extension 放宽条件：
  - `pattern_quality >= 70`
  - `setup_score >= 45`
  - `relative_strength_score >= 60`
  - 周线趋势不为 down

BTC 不使用这条放宽规则。

## 当前默认参数

- `execution_mode = daily`
- `risk_per_trade = 3%`
- `min_setup_score = 60`
- `min_pattern_quality = 40`
- `partial_exit_pct = 0`
- `leverage = 1.0`
- `fee_rate = 0.1%`
- `slippage_rate = 0.05%`
- `funding_rate_annual = 10%`

## v0.8 决策路径

BTC 使用「15% 趋势底仓 + 85% 信号层」的组合路径，信号层启用
`use_btc_exit_final`。BTC 最终出场规则是：

- 亏损仓位：`2 x ATR` 硬止损、入场结构破位、45 天且亏损超过 1% 时间止损。
- 盈利仓位：默认禁用 ATR 跟踪，用最近 10 根低点构成的动态结构止损。
- 盈利仓位不做时间止损；从最高浮盈回吐 35% 才全平。
- 均线破位只减仓 30%，不清仓。

ETH 改为 `ETHStrategyV3` 纯底仓模式：周线 `EMA20 > EMA50` 且日线高于 SMA200
时持有 20% 底仓；普通周期信号全部忽略。只有 `setup_score >= 85` 且
`pattern_quality >= 85` 的极端信号才加 5%，每年最多 2 次。本次全期回测未触发
极端例外加仓。

这意味着 ETH 的 Go/No-Go 实际验证的是「42% 被动底仓 + 成本」的收益特征，
而不是入场信号逻辑。85/85 阈值经历 COVID、Luna、FTX 三次极端事件仍未触发，
要么是刻意保守，要么是死代码。模拟盘结束后需要确认。

v0.9 起 ETH V3 已接入 `backtest_with_fixes.py` 的成本管道，包含手续费
（0.1% 每边）、滑点和资金费率（10% 年化）。此前 v0.8 快照中的 ETH V3 指标
未含成本，仅作参考。

### v0.8 最终决策快照

时间范围：`2020-01-01` 到 `2026-09-04`。复现入口：
`python scripts/final_decision.py`。

| 标的 | 总收益 | Sharpe | 最大回撤 | 暴露 | Calmar | 备注 |
|---|---:|---:|---:|---:|---:|---|
| BTC 组合 | `+100.23%` | `1.028` | `-12.81%` | `42.15%` | `~0.85` | 42 笔信号层交易，信号 IR `0.760` |
| BTC 买入持有 | `+1023.45%` | `~0.7`（估） | `~-77%` | `100%` | `~0.57` | 同期，策略在风险调整口径可能胜出 |
| ETH V3 | `+61.39%` | `0.701` | `-15.49%` | `42.76%` | `~0.48` | 纯底仓含成本，年化 `7.43%`，未触发例外加仓 |

BTC Walk-forward：28 折，9 折为正，一致性 `32.1%`。蒙特卡洛 10,000 次：
盈利概率 `96.93%`，权益低于 50% 的概率 `0%`，平均最大回撤 `-7.09%`。

注意：蒙特卡洛的 96.93% 是对全样本收益分布的 in-sample bootstrap，不反映
参数不稳定性。Walk-forward 32.1% 才是样本外证据。两者口径不同：MC 量化
"如果历史分布重复，盈利概率多大"；WF 量化"参数在未见数据上是否稳定"。

Go/No-Go 清单：`9/9` 通过，脚本建议进入 60 天模拟盘。但 Walk-forward 仍低于
50%，实盘或模拟盘必须使用小仓位，并把执行偏差作为最高优先级观察项。

### 60 天模拟盘预期与成功标准

60 天内期望信号数约 `0.7–0.8` 个/标的（BTC ~4.3 笔/年，ETH ~4.8 笔/年）。
模拟盘的定位是**管道验证**，不是策略 edge 验证。

能验证的：

- 零 repaint 事件（机检标准：每日 `daily_state` 的 `last_bar` ≤ 最近已收盘日）
- `state.json` 按收盘 K 线推进，无跳跃或遗漏
- 填充价与 T+1 开盘价偏差 < `0.5%`（长期均值；若 60 天零成交则此项 N/A）
- 模拟盘状态转换与手工核对一致（每周核对一次）

不能验证的：

- 策略 edge（0-2 个样本不具统计意义）
- WF 一致性是否为真实特征

### v0.9 滑点敏感性

复现入口：`python scripts/slippage_sensitivity.py`。

| 标的 | 滑点 | 总收益 | Sharpe | 最大回撤 |
|---|---:|---:|---:|---:|
| BTC | 0.05% | `+100.23%` | `1.028` | `-12.81%` |
| BTC | 0.10% | `+97.76%` | `1.010` | `-12.82%` |
| BTC | 0.20% | `+88.85%` | `0.943` | `-12.84%` |
| ETH V3 | 0.05% | `+61.39%` | `0.701` | `-15.49%` |
| ETH V3 | 0.10% | `+61.17%` | `0.699` | `-15.58%` |
| ETH V3 | 0.20% | `+60.72%` | `0.695` | `-15.77%` |

结论：BTC 对滑点较敏感（交易频率高），0.2% 滑点时 Sharpe 跌破 1；ETH V3 交易
频率低，滑点影响可忽略。基准成本假设：手续费 0.1% 每边 + 滑点（如表）+
资金费率 10% 年化。

## 最近回测结果

### 当前主基线：2020-01-01 到 2026-09-04

数据文件已扩展为 `data/BTC_1d.csv` 和 `data/ETH_1d.csv`。

#### BTC

- 策略收益：约 `+96.45%`
- 买入持有：约 `+1023.45%`
- 年化收益：约 `+10.63%`
- Sharpe：`0.950`
- Sortino：`1.542`
- Calmar：`0.969`
- 最大回撤：约 `-10.97%`
- 交易数：29
- 胜率：44.83%
- 盈亏比：3.477
- 仓位暴露：约 `25.83%`

Walk-forward：

- 训练窗口：365 天
- 测试窗口：90 天
- 折数：28
- 样本外为正的折数：约 10 / 28

#### ETH

- 策略收益：约 `+52.24%`
- 买入持有：约 `+1842.40%`
- 年化收益：约 `+6.49%`
- Sharpe：`0.565`
- Sortino：`0.930`
- Calmar：`0.272`
- 最大回撤：约 `-23.84%`
- 交易数：32
- 胜率：37.50%
- 盈亏比：1.558
- 仓位暴露：约 `27.39%`

Walk-forward：

- 训练窗口：365 天
- 测试窗口：90 天
- 折数：28
- 样本外为正的折数：约 5 / 28

结论：样本量已经达到 30 笔左右，但 walk-forward 显示参数稳定性仍不足，策略显著
跑输买入持有。P4-P6 模块先作为独立组件保留，不建议在当前证据下全部接入主回测。

### 历史小样本结果

时间范围：`2024-09-04` 到 `2026-09-04`

注意：最后一根日线如果在更新当天尚未收盘，应只使用已收盘 K 线做最终结论。

### ETH

- 策略收益：约 `+5.10%`
- 买入持有：约 `+3.58%`
- 交易数：7
- 胜率：14.29%
- 最大回撤：约 `-11.22%`
- 仓位暴露：约 `23.94%`

注意：ETH 有一笔当前未平仓仓位，收益包含浮盈；已平仓交易质量仍偏弱。

### BTC

- 策略收益：约 `+15.57%`
- 买入持有：约 `+41.24%`
- 交易数：8
- 胜率：37.5%
- 最大回撤：约 `-10.95%`
- 仓位暴露：约 `22.98%`

## 已解决问题（归档）

以下问题在 v0.3–v0.9 中已解决：

1. 样本量从 7-8 笔扩展到 BTC 42 笔 / ETH 32 笔。
2. 风险调整指标（Sharpe / Sortino / Calmar）已由 `metrics.py` 提供。
3. 数据完整性校验已由 `scripts/validate_data.py` 实现。
4. 代码已提交到 GitHub（commit `330db01` 起），复现性闭环。
5. Walk-forward 已在 daily 模式下完整重跑 28 折（v0.7–v0.8）。
6. BTC 出场过早问题由 `BTCExitFinal` 动态结构出场改善。
7. ETH accumulation 低质量入场由 `ETHFixManager` 过滤。

## 当前未决问题

1. 资金费率仍是固定年化 10% 假设，未接入历史 funding rate 序列。
2. Walk-forward 一致性 BTC `9/28`（32.1%）仍低于 50%。
3. ETH V3 极端例外（85/85）从未触发，入场信号逻辑未被数据验证。
4. `ETHStrategyV3` 是独立策略层，尚未替换主 `cycle.py` 入场引擎。
5. 底仓 vs 信号层的收益归因还未拆分。
6. BTC 和 ETH 跑的是两套策略，Sharpe 差距无法归因。

## 优化原则

1. **不要直接提高 `risk_per_trade` 来追绝对收益。**  
   低暴露来自周期和形态过滤；提高单笔风险会增加单笔亏损，而不是提高信号质量。
2. **名义暴露和风险预算要分开。**  
   `markup` 阶段可以在高质量 setup 下提高仓位上限，但仍应受单笔风险约束。
3. **ETH 先逐笔复盘，再提高门槛。**  
   直接把 `min_setup_score` 提到 70 可能把样本砍得过少，不一定解决出场问题。
4. **低胜率不一定失败。**  
   需要结合盈亏比、期望收益、最大连续亏损和风险调整指标判断。

## 优先级路线图

| 优先级 | 任务 | 说明 |
|---|---|---|
| P0 | 补齐回测指标 | 增加 Sharpe / Sortino、年化收益、平均盈亏比、最大连续亏损、恢复时间。 |
| P0 | 重跑最新 `daily` walk-forward | 使用当前 ETH profile 和默认参数，确认是否存在过拟合。 |
| P0 | 数据完整性校验 | 增加 K 线缺失、重复时间戳、异常跳空、零成交量、最后一根未收盘检查。 |
| P0 | 首次提交项目快照 | 提交后把 commit hash 写回本文档，保证回测可复现。 |
| P1 | 扩大回测区间 | 从 2021 年或更早开始，用滚动样本外验证，而不是全区间调参。 |
| P1 | 结构止损 | 测试跌破最近 swing low 离场。 |
| P1 | 均线离场 | 日线收盘跌破 EMA20 先减仓，次日未收回继续减；跌破 EMA50 清仓。 |
| P1 | 时间止损 | 持仓超过 N 根 K 线仍未产生足够浮盈时降风险，但避免变成短期策略。 |
| P1 | OKX 历史 funding rate | 按 8 小时结算映射到日线，替代固定 `funding_rate_annual`。 |
| P2 | 分批止盈 | 只在衰竭扩张、前高附近或高质量形态触发；不要所有持仓固定比例减仓。 |
| P2 | 周期状态仓位 | `accumulation` 只允许高质量反转小仓试探；`recovery` 半仓；`markup` 提高名义暴露；`distribution` 只减不加；`markdown` 禁多。 |
| P2 | 滑点敏感性 | 测试 0.05% / 0.10% / 0.20%。 |
| P3 | 工程测试 | 补状态机转换、ATR 为零、funding 计算、强平逻辑等测试。 |
| P3 | CI / 本地检查 | 如果有远端仓库，用 GitHub Actions；本地可先加 pytest + mypy。 |
| P3 | 回测日志 | 记录每笔入场/出场原因和当时的指标快照。 |
| P3 | 文档合并 | 如存在多份 handoff，合并为单一入口，其他文件只保留链接。 |

## 实盘前检查清单

- [ ] 最新 `daily` 模式 walk-forward 完整通过。
- [ ] 扩大到 2021 年后的滚动样本外回测完成。
- [ ] 接入真实 funding rate 后收益变化可控。
- [ ] 滑点 0.05% / 0.10% / 0.20% 敏感性分析完成。
- [ ] 最大连续亏损和单笔最大亏损满足风控。
- [ ] 模拟盘运行足够时间，结果与回测偏差可解释。
- [ ] 交易所 API 断线重连、订单超时、仓位对账和紧急平仓逻辑完成。
- [ ] 实盘杠杆、保证金模式、强平价和资金费率结算时间核对完成。

## 验证状态

`python -m pytest` 当前通过，共 21 个测试。  
`python scripts/final_decision.py` 已完整跑通，输出 v0.8 快照。
`python scripts/slippage_sensitivity.py` 已完整跑通，输出三档滑点对比。

## Changelog

### v0.9 - 2026-09-04

- ETH V3 接入 `backtest_with_fixes.py` 主管道，加入手续费、滑点和资金费率。
  收益从 v0.8 无成本的 `+71.53%` 修正为含成本的 `+61.39%`。
- 新增 `scripts/slippage_sensitivity.py`，对 BTC 和 ETH V3 跑三档滑点。
  BTC 在 0.2% 滑点时 Sharpe 降至 0.943；ETH V3 对滑点不敏感。
- 新增 `.github/workflows/ci.yml`，push/PR 自动跑 pytest（Python 3.11/3.12）。
- `scripts/final_decision.py` 改走主管道调用 ETH V3，移除独立计算路径。
- `CycleConfig` 新增 `use_eth_strategy_v3` 标志。

### v0.8 - 2026-09-04

- 新增 `crypto_trading_agents/eth_strategy_v3.py`，ETH 降级为纯底仓模式，
  普通信号层禁用，仅保留 85/85 极端例外。
- 新增 `crypto_trading_agents/btc_exit_final.py`：盈利仓位改用动态结构出场，
  禁用盈利仓位的 ATR 跟踪和时间止损；亏损仓位继续快速止损。
- 主回测新增 `use_btc_exit_final` 开关，启用时绕过旧阶段出场和 ATR 跟踪路径。
- 新增 `scripts/final_decision.py`，组合回测、数据校验、Walk-forward、
  蒙特卡洛和 Go/No-Go 检查。
- 更新 `scripts/backtest_with_fixes.py`，支持 BTC 最终出场开关。
- 最终决策结果：BTC 组合收益 `+100.23%`、Sharpe `1.028`、最大回撤
  `-12.81%`；ETH V3 收益 `+71.53%`、Sharpe `0.783`、最大回撤 `-13.55%`。
- 蒙特卡洛显示 BTC 盈利概率 `96.93%`；Walk-forward 一致性 `32.1%`，
  仍不建议直接实盘，建议先跑 60 天模拟盘。

### v0.7 - 2026-09-04

- 新增 `scripts/walk_forward_with_fixes.py`，对比基线与修复后的滚动样本外表现。
- 新增 `scripts/attribution_analysis.py`，输出分年度、Alpha/Beta 与市场阶段归因。
- Walk-forward 初步结果：
  - BTC：28 折，正收益窗口 8/28；累计约 `+86.43%`；平均 Sharpe `0.174`。
  - ETH：28 折，正收益窗口 11/28；累计约 `+41.92%`；平均 Sharpe `-0.182`。
- 归因结果：
  - BTC：底仓贡献约 `+44.40%`，信号层贡献约 `+35.47%`，信号层信息比率 `0.734`。
  - ETH：底仓贡献约 `+45.53%`，信号层仅 `+2.36%`，信息比率 `0.091`。
- 结论：修复有效提高了暴露和 ETH 样本外表现，但两类资产仍大幅跑输买入持有；
  ETH 的信号层 Alpha 很弱，需要继续观察或降低仓位。

### v0.6 - 2026-09-04

- 新增 `exit_optimizer.py`、`trend_base_simple.py` 和 `eth_fix.py`。
- 主回测增加可选开关：`use_exit_optimizer`、`use_eth_fix`、`recovery_position_multiplier`。
- ETH Reversal Extension 增加强化条件参数。
- 修复 exit optimizer 下 `holding_days` 未累计的问题。
- 新增 `scripts/backtest_with_fixes.py`，用于验证出场优化、ETH 过滤和趋势底仓。
- 初步验证结果：
  - BTC：收益约 `+85.91%`，Sharpe `1.071`，最大回撤 `-12.68%`，暴露约 `43.05%`。
  - ETH：收益约 `+59.54%`，Sharpe `0.770`，最大回撤 `-20.05%`，暴露约 `37.02%`。
- 测试扩展到 21 个。

### v0.4 - 2026-09-04

### v0.5 - 2026-09-04

- 新增 `scripts/trade_review.py`，支持逐笔交易复盘、MFE/MAE 和分组诊断。
- 新增 `scripts/exposure_analysis.py`，量化空仓成本和持仓期间相对基准表现。
- 新增 `scripts/param_stability_check.py`，对核心参数做扰动测试。
- `CycleTrade` 增加 MFE/MAE。
- `CycleBacktestResult` 增加日收益序列和每日持仓标记。
- 修复 `stop_atr_multiple` / `trail_atr_multiple` 在关闭 asset profile 时无效的问题。
- 完成 BTC / ETH 2020-2026 逐笔复盘、暴露分析和参数稳定性检查。

### v0.4 - 2026-09-04

- 扩展 BTC / ETH 日线数据至 2020-01-01。
- 跑通 2020-2026 主基线，交易数提升到 29 / 32 笔。
- 补充 Sharpe / Sortino / Calmar / 暴露调整年化收益。
- 完成 365/90 walk-forward 初步验证。
- 新增 P4：`multi_timeframe.py`、`adaptive_exit.py`。
- 新增 P5：`monte_carlo.py`、`trend_base.py`、`sentiment_filter.py`。
- 新增 P6：`portfolio_risk.py`。
- 增加 P4-P6 基础测试。
- 明确 P4-P6 模块暂不接入主回测，等待基线和 walk-forward 证据。

### v0.3 - 2026-09-04

- 新增风险调整指标模块 `metrics.py`。
- 新增出场管理模块 `exit_manager.py`。
- 新增分层入场模块 `entry_manager.py`。
- 新增 OHLCV 数据校验脚本 `scripts/validate_data.py`。
- 新增优化模块集成示例 `scripts/backtest_with_optimizations.py`。
- 主回测结果接入 `risk_metrics`，并在回测前执行数据校验。
- 新增 `data/` 目录用于本地 CSV 数据。

### v0.2 - 2026-09-04

- 增加版本号、更新日期和回测快照说明。
- 明确策略目标是风险调整收益，而不是单纯追逐绝对收益。
- 增加 P0-P3 优先级路线图。
- 增加实盘前检查清单。
- 说明名义暴露与风险预算需要分开管理。
- 说明 `accumulation` 不应一刀切禁止交易，只允许高质量反转小仓试探。

### v0.1 - 2026-09-04

- 初版交接摘要。

## 免责声明

项目仅用于研究和回测，不构成投资建议。加密资产波动性高，实盘前必须自行验证数据、
成本、风控和执行路径。
