"""风险调整回测指标。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class RiskMetrics:
    """回测风险指标汇总。"""

    total_return: float = 0.0
    annual_return: float = 0.0
    sharpe_ratio: float = 0.0
    sortino_ratio: float = 0.0
    calmar_ratio: float = 0.0
    max_drawdown: float = 0.0
    max_drawdown_duration_days: int = 0
    max_consecutive_losses: int = 0
    max_consecutive_wins: int = 0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    avg_win_loss_ratio: float = 0.0
    total_trades: int = 0
    exposure_pct: float = 0.0
    exposure_adjusted_annual_return: float = 0.0
    volatility_annual: float = 0.0
    downside_volatility_annual: float = 0.0

    def summary(self) -> str:
        """返回格式化指标摘要。"""
        return "\n".join(
            [
                "=" * 52,
                "风险调整回测指标",
                "=" * 52,
                f"总收益率:         {self.total_return:10.2%}",
                f"年化收益率:       {self.annual_return:10.2%}",
                f"Sharpe Ratio:     {self.sharpe_ratio:10.3f}",
                f"Sortino Ratio:    {self.sortino_ratio:10.3f}",
                f"Calmar Ratio:     {self.calmar_ratio:10.3f}",
                f"最大回撤:         {self.max_drawdown:10.2%}",
                f"回撤持续天数:     {self.max_drawdown_duration_days:10d}",
                f"最大连续亏损:     {self.max_consecutive_losses:10d}",
                f"最大连续盈利:     {self.max_consecutive_wins:10d}",
                f"胜率:             {self.win_rate:10.2%}",
                f"盈亏比:           {self.profit_factor:10.3f}",
                f"平均盈亏比:       {self.avg_win_loss_ratio:10.3f}",
                f"总交易数:         {self.total_trades:10d}",
                f"仓位暴露:         {self.exposure_pct:10.2%}",
                f"暴露调整年化收益: {self.exposure_adjusted_annual_return:10.2%}",
                f"年化波动率:       {self.volatility_annual:10.2%}",
                f"年化下行波动率:   {self.downside_volatility_annual:10.2%}",
                "=" * 52,
            ]
        )


def compute_risk_metrics(
    daily_returns: pd.Series,
    risk_free_rate: float = 0.0,
    periods_per_year: int = 365,
    trade_pnl_list: Optional[list[float]] = None,
) -> RiskMetrics:
    """根据日收益序列和交易盈亏列表计算风险调整指标。"""
    if daily_returns is None or len(daily_returns) == 0:
        return RiskMetrics()

    returns = pd.Series(daily_returns).dropna().astype(float)
    if len(returns) < 2:
        return RiskMetrics()

    cumulative = (1 + returns).cumprod()
    total_return = cumulative.iloc[-1] - 1.0
    annual_return = (1 + total_return) ** (periods_per_year / len(returns)) - 1.0

    daily_risk_free = risk_free_rate / periods_per_year
    excess_returns = returns - daily_risk_free
    volatility = returns.std(ddof=0) * np.sqrt(periods_per_year)
    downside_returns = returns.clip(upper=0)
    downside_deviation = downside_returns.std(ddof=0) * np.sqrt(periods_per_year)

    sharpe = (
        np.sqrt(periods_per_year) * excess_returns.mean() / returns.std(ddof=0)
        if returns.std(ddof=0) > 1e-12
        else 0.0
    )
    sortino = (
        np.sqrt(periods_per_year) * excess_returns.mean() / downside_returns.std(ddof=0)
        if downside_returns.std(ddof=0) > 1e-12
        else 0.0
    )

    peak = cumulative.cummax()
    drawdown = (cumulative - peak) / peak
    max_drawdown = drawdown.min()
    max_drawdown_duration = _max_drawdown_duration(drawdown)
    calmar = (
        annual_return / abs(max_drawdown)
        if abs(max_drawdown) > 1e-12
        else 0.0
    )

    total_trades = 0
    win_rate = 0.0
    profit_factor = 0.0
    avg_win_loss_ratio = 0.0
    max_consecutive_losses = _max_consecutive((returns < 0).to_numpy())
    max_consecutive_wins = _max_consecutive((returns > 0).to_numpy())

    if trade_pnl_list:
        pnl = np.asarray(trade_pnl_list, dtype=float)
        wins = pnl[pnl > 0]
        losses = pnl[pnl < 0]
        total_trades = len(pnl)
        win_rate = len(wins) / len(pnl)
        if losses.size and losses.sum() != 0:
            profit_factor = wins.sum() / abs(losses.sum())
        elif wins.sum() > 0:
            profit_factor = float("inf")
        if wins.size and losses.size:
            avg_win_loss_ratio = wins.mean() / abs(losses.mean())
        elif wins.size:
            avg_win_loss_ratio = float("inf")
        max_consecutive_losses = _max_consecutive(pnl < 0)
        max_consecutive_wins = _max_consecutive(pnl > 0)

    exposure = (returns != 0).mean()
    exposure_adjusted_return = annual_return / exposure if exposure > 0 else 0.0

    return RiskMetrics(
        total_return=total_return,
        annual_return=annual_return,
        sharpe_ratio=sharpe,
        sortino_ratio=sortino,
        calmar_ratio=calmar,
        max_drawdown=max_drawdown,
        max_drawdown_duration_days=max_drawdown_duration,
        max_consecutive_losses=max_consecutive_losses,
        max_consecutive_wins=max_consecutive_wins,
        win_rate=win_rate,
        profit_factor=profit_factor,
        avg_win_loss_ratio=avg_win_loss_ratio,
        total_trades=total_trades,
        exposure_pct=exposure,
        exposure_adjusted_annual_return=exposure_adjusted_return,
        volatility_annual=volatility,
        downside_volatility_annual=downside_deviation,
    )


def compare_with_benchmark(
    strategy_returns: pd.Series,
    benchmark_returns: pd.Series,
    risk_free_rate: float = 0.0,
) -> dict[str, str]:
    """返回策略与基准的核心指标对比。"""
    strategy = compute_risk_metrics(strategy_returns, risk_free_rate)
    benchmark = compute_risk_metrics(benchmark_returns, risk_free_rate)
    return {
        "strategy_annual_return": f"{strategy.annual_return:.2%}",
        "benchmark_annual_return": f"{benchmark.annual_return:.2%}",
        "excess_annual_return": f"{strategy.annual_return - benchmark.annual_return:.2%}",
        "strategy_sharpe": f"{strategy.sharpe_ratio:.3f}",
        "benchmark_sharpe": f"{benchmark.sharpe_ratio:.3f}",
        "strategy_max_drawdown": f"{strategy.max_drawdown:.2%}",
        "benchmark_max_drawdown": f"{benchmark.max_drawdown:.2%}",
        "strategy_calmar": f"{strategy.calmar_ratio:.3f}",
        "benchmark_calmar": f"{benchmark.calmar_ratio:.3f}",
        "strategy_exposure": f"{strategy.exposure_pct:.2%}",
    }


def _max_drawdown_duration(drawdown: pd.Series) -> int:
    """计算最大连续处于回撤状态的天数。"""
    max_duration = 0
    current_duration = 0
    for is_drawdown in (drawdown < 0).tolist():
        current_duration = current_duration + 1 if is_drawdown else 0
        max_duration = max(max_duration, current_duration)
    return max_duration


def _max_consecutive(values: np.ndarray) -> int:
    """计算布尔数组中连续 True 的最大长度。"""
    max_run = 0
    current_run = 0
    for value in values:
        current_run = current_run + 1 if value else 0
        max_run = max(max_run, current_run)
    return max_run
