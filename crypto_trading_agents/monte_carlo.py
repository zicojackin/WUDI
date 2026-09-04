"""蒙特卡洛模拟与参数敏感性分析。"""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import product
from typing import Callable, Optional

import numpy as np
import pandas as pd


@dataclass(slots=True)
class MonteCarloConfig:
    n_simulations: int = 10000
    confidence_levels: list[float] = field(default_factory=lambda: [0.05, 0.25, 0.50, 0.75, 0.95])
    initial_capital: float = 10000.0
    random_seed: int = 42


@dataclass(slots=True)
class MonteCarloResult:
    final_equities: np.ndarray
    max_drawdowns: np.ndarray
    ruin_flags: np.ndarray
    confidence_intervals: dict[float, tuple[float, float]]
    stats: dict

    def summary(self) -> str:
        lines = [
            "=" * 52,
            "蒙特卡洛模拟",
            "=" * 52,
            f"模拟次数: {len(self.final_equities)}",
            f"最终权益均值: {np.mean(self.final_equities):,.2f}",
            f"最终权益中位数: {np.median(self.final_equities):,.2f}",
            f"盈利概率: {self.stats['prob_profit']:.2%}",
            f"权益低于 50% 的概率: {self.stats['prob_ruin']:.2%}",
            f"平均最大回撤: {np.mean(self.max_drawdowns):.2%}",
        ]
        for level, (low, high) in sorted(self.confidence_intervals.items()):
            lines.append(f"{level:.0%} 区间: [{low:,.2f}, {high:,.2f}]")
        return "\n".join(lines)


class MonteCarloSimulator:
    """用交易序列 bootstrap 评估策略置信区间。"""

    def __init__(self, config: Optional[MonteCarloConfig] = None):
        self.config = config or MonteCarloConfig()

    def bootstrap_simulation(
        self,
        trade_pnl_list: list[float],
        n_trades_per_sim: Optional[int] = None,
    ) -> MonteCarloResult:
        if len(trade_pnl_list) < 3:
            raise ValueError("至少需要 3 笔交易才能进行蒙特卡洛模拟")

        pnl = np.asarray(trade_pnl_list, dtype=float)
        n_trades = len(pnl) if n_trades_per_sim is None else n_trades_per_sim
        rng = np.random.default_rng(self.config.random_seed)
        initial_capital = self.config.initial_capital
        final_equities = np.empty(self.config.n_simulations)
        max_drawdowns = np.empty(self.config.n_simulations)
        ruin_flags = np.zeros(self.config.n_simulations)

        for simulation in range(self.config.n_simulations):
            sampled = rng.choice(pnl, size=n_trades, replace=True)
            equity = initial_capital
            peak = initial_capital
            max_drawdown = 0.0
            for pnl_value in sampled:
                equity *= 1.0 + pnl_value
                peak = max(peak, equity)
                max_drawdown = min(max_drawdown, (equity - peak) / peak)
                if equity < initial_capital * 0.5:
                    ruin_flags[simulation] = 1.0
                    break
            final_equities[simulation] = equity
            max_drawdowns[simulation] = max_drawdown

        confidence_intervals = {
            level: (
                float(np.percentile(final_equities, (1 - level) / 2 * 100)),
                float(np.percentile(final_equities, (1 + level) / 2 * 100)),
            )
            for level in self.config.confidence_levels
        }
        stats = {
            "initial_capital": initial_capital,
            "n_simulations": self.config.n_simulations,
            "n_trades_per_sim": n_trades,
            "prob_profit": float((final_equities > initial_capital).mean()),
            "prob_ruin": float(ruin_flags.mean()),
        }
        return MonteCarloResult(final_equities, max_drawdowns, ruin_flags, confidence_intervals, stats)


class ParameterSensitivityAnalyzer:
    """对回测函数做参数网格扫描，评估参数是否处于平坦区域。"""

    def __init__(self):
        self.results: list[dict] = []

    def analyze(
        self,
        backtest_fn: Callable,
        frame: pd.DataFrame,
        param_ranges: dict[str, list],
        fixed_params: Optional[dict] = None,
    ) -> pd.DataFrame:
        fixed_params = fixed_params or {}
        self.results = []
        names = list(param_ranges)
        total = int(np.prod([len(values) for values in param_ranges.values()]))
        print(f"[Sensitivity] 参数组合数: {total}")

        for values in product(*param_ranges.values()):
            params = dict(zip(names, values))
            try:
                result = backtest_fn(frame, **params, **fixed_params)
                returns = pd.Series(result["daily_returns"]).dropna()
                cumulative = (1 + returns).cumprod()
                drawdown = ((cumulative - cumulative.cummax()) / cumulative.cummax()).min()
                self.results.append(
                    {
                        **params,
                        "sharpe": self._sharpe(returns),
                        "total_return": cumulative.iloc[-1] - 1.0,
                        "max_drawdown": drawdown,
                        "n_trades": len(result.get("trades", [])),
                    }
                )
            except Exception as error:
                self.results.append({**params, "sharpe": np.nan, "error": str(error)})

        return pd.DataFrame(self.results)

    def _sharpe(self, returns: pd.Series) -> float:
        if len(returns) < 2 or returns.std(ddof=0) <= 1e-12:
            return 0.0
        return float(np.sqrt(365.0) * returns.mean() / returns.std(ddof=0))
