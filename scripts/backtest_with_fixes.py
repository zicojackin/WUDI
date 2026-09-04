"""验证出场优化、ETH 过滤和趋势底仓的简化集成脚本。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

from crypto_trading_agents.cycle import CycleConfig, backtest_cycle, prepare_cycle_frame
from crypto_trading_agents.eth_fix import ETHFixConfig
from crypto_trading_agents.exit_optimizer import (
    create_btc_exit_optimizer,
    create_eth_exit_optimizer,
)
from crypto_trading_agents.metrics import compute_risk_metrics
from crypto_trading_agents.trend_base_simple import TrendBaseSimple, weekly_frame_from_daily


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.validate_data import validate_ohlcv_frame


def load_data(args: argparse.Namespace) -> pd.DataFrame:
    if args.data_file:
        return pd.read_csv(args.data_file)
    from scripts.backtest_cycle_full import fetch_klines

    return fetch_klines(args.symbol, "1d", args.start, args.end)


def run_backtest_with_fixes(
    frame: pd.DataFrame,
    start: str,
    end: str,
    symbol: str,
    use_exit_optimizer: bool = False,
    use_eth_fix: bool = False,
    use_eth_exit_v2: bool = False,
    use_trend_base: bool = False,
    use_btc_exit_final: bool = False,
    base_position_pct: float = 0.15,
) -> dict:
    """返回信号层、底仓层和组合层的日收益，供 walk-forward 与归因复用。"""
    symbol = symbol.upper()
    validation = validate_ohlcv_frame(frame, symbol)
    if not validation["passed"]:
        raise ValueError(f"数据校验失败: {validation['issues']}")

    config = CycleConfig(
        execution_mode="daily",
        risk_per_trade=0.03,
        use_exit_optimizer=use_exit_optimizer,
        use_eth_fix=use_eth_fix and symbol == "ETHUSDT",
        use_eth_exit_v2=use_eth_exit_v2 and symbol == "ETHUSDT",
        use_btc_exit_final=use_btc_exit_final and symbol == "BTCUSDT",
        recovery_position_multiplier=0.5 if use_eth_fix else 1.0,
    )
    result = backtest_cycle(frame, start, end, config, symbol=symbol)
    signal_returns = pd.Series(
        [row["return"] for row in result.daily_returns],
        index=pd.to_datetime([row["date"] for row in result.daily_returns]),
    )

    base_returns = pd.Series(0.0, index=signal_returns.index)
    if use_trend_base:
        prepared = prepare_cycle_frame(frame, config, symbol=symbol)
        weekly = weekly_frame_from_daily(frame)
        weekly_index = {date.date(): row for date, row in weekly.iterrows()}
        base = TrendBaseSimple(position_pct=base_position_pct)
        active_flags: list[bool] = []
        for row in prepared.itertuples(index=False):
            bar = row._asdict()
            current_date = pd.Timestamp(bar["date"])
            base.on_bar(bar, weekly_index.get(current_date.date()))
            active_flags.append(base.state.is_open)

        close_returns = prepared.set_index("date")["close"].pct_change().fillna(0.0)
        active_series = pd.Series(active_flags, index=prepared["date"])
        base_returns = close_returns * base_position_pct * active_series.shift(1).fillna(False)

    signal_weight = 1.0 - base_position_pct if use_trend_base else 1.0
    combined_returns = signal_returns * signal_weight + base_returns
    metrics = compute_risk_metrics(combined_returns)
    return {
        "config": config,
        "result": result,
        "signal_returns": signal_returns,
        "base_returns": base_returns,
        "combined_returns": combined_returns,
        "metrics": metrics,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="验证修复后的双层策略")
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--start", default="2020-01-01")
    parser.add_argument("--end", default="2026-09-04")
    parser.add_argument("--data-file")
    parser.add_argument("--use-exit-optimizer", action="store_true")
    parser.add_argument("--use-eth-fix", action="store_true")
    parser.add_argument("--use-eth-exit-v2", action="store_true")
    parser.add_argument("--use-trend-base", action="store_true")
    parser.add_argument("--use-btc-exit-final", action="store_true")
    parser.add_argument("--base-position-pct", type=float, default=0.15)
    args = parser.parse_args()

    symbol = args.symbol.upper()
    frame = load_data(args)
    output = run_backtest_with_fixes(
        frame,
        args.start,
        args.end,
        symbol,
        use_exit_optimizer=args.use_exit_optimizer,
        use_eth_fix=args.use_eth_fix,
        use_eth_exit_v2=args.use_eth_exit_v2,
        use_trend_base=args.use_trend_base,
        use_btc_exit_final=args.use_btc_exit_final,
        base_position_pct=args.base_position_pct,
    )
    metrics = output["metrics"]
    print(f"\n{symbol} 修复组合结果")
    print(f"  exit_optimizer={args.use_exit_optimizer}")
    print(f"  eth_fix={output['config'].use_eth_fix}")
    print(f"  trend_base={args.use_trend_base}")
    print(f"  trades={output['result'].trade_count}")
    print(f"  total_return={metrics.total_return:.2%}")
    print(f"  annual_return={metrics.annual_return:.2%}")
    print(f"  sharpe={metrics.sharpe_ratio:.3f}")
    print(f"  sortino={metrics.sortino_ratio:.3f}")
    print(f"  max_drawdown={metrics.max_drawdown:.2%}")
    print(f"  exposure={metrics.exposure_pct:.2%}")


if __name__ == "__main__":
    main()
