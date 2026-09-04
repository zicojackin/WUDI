from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass, field, replace
from typing import Any

import numpy as np
import pandas as pd

from .metrics import RiskMetrics, compute_risk_metrics
from .exit_optimizer import ExitOptimizer, create_btc_exit_optimizer, create_eth_exit_optimizer
from .eth_fix import ETHFixConfig, ETHFixManager
from .eth_exit_v2 import ETHExitV2
from .btc_exit_final import BTCExitFinal


LONG_STAGES = {
    "reversal_extension",
    "wedge_pop",
    "ema_crossback",
    "base_n_break",
}

CYCLE_STATES = ("unknown", "accumulation", "recovery", "markup", "distribution", "markdown")

STAGE_STATE_MAP = {
    "reversal_extension": "accumulation",
    "wedge_pop": "recovery",
    "ema_crossback": "recovery",
    "base_n_break": "markup",
    "exhaustion_extension": "distribution",
    "wedge_drop": "markdown",
    "ema_crossback_downside": "markdown",
    "base_n_break_downside": "markdown",
}

CYCLE_NEXT_STATES = {
    "unknown": set(CYCLE_STATES),
    "accumulation": {"accumulation", "recovery", "markup"},
    "recovery": {"recovery", "markup", "accumulation"},
    "markup": {"markup", "distribution", "recovery"},
    "distribution": {"distribution", "markdown", "markup"},
    "markdown": {"markdown", "accumulation", "recovery"},
}

ENTRY_STATE_MAP = {
    "reversal_extension": {"markdown", "distribution", "accumulation"},
    "wedge_pop": {"markdown", "accumulation", "recovery"},
    "ema_crossback": {"accumulation", "recovery", "markup"},
    "base_n_break": {"recovery", "markup"},
}

PHASE_POSITION_FRACTION = {
    "reversal_extension": 0.35,
    "wedge_pop": 0.55,
    "ema_crossback": 0.70,
    "base_n_break": 1.00,
}

PHASE_STOP_ATR = {
    "reversal_extension": 1.5,
    "wedge_pop": 2.0,
    "ema_crossback": 2.0,
    "base_n_break": 2.5,
}

PHASE_TRAIL_ATR = {
    "reversal_extension": 2.0,
    "wedge_pop": 2.5,
    "ema_crossback": 3.0,
    "base_n_break": 3.5,
}

ASSET_PROFILES = {
    "ETHUSDT": {
        "phase_stop_atr": {
            "reversal_extension": 2.0,
            "wedge_pop": 2.0,
            "ema_crossback": 2.0,
            "base_n_break": 2.0,
        },
        "phase_trail_atr": {
            "reversal_extension": 3.0,
            "wedge_pop": 3.0,
            "ema_crossback": 3.0,
            "base_n_break": 3.0,
        },
        "relaxed_reversal": {
            "pattern_quality": 70.0,
            "setup_score": 45.0,
        },
    },
}

EXECUTION_MODES = ("daily", "4h")


@dataclass(slots=True)
class CycleConfig:
    execution_mode: str = "daily"
    fee_rate: float = 0.001
    slippage_rate: float = 0.0005
    funding_rate_annual: float = 0.10
    leverage: float = 1.0
    maintenance_margin_rate: float = 0.005
    max_position_fraction: float = 1.0
    risk_per_trade: float = 0.03
    min_setup_score: float = 60.0
    use_asset_profile: bool = True
    stop_atr_multiple: float = 2.0
    trail_atr_multiple: float = 3.0
    exhaustion_atr: float = 2.5
    reversal_atr: float = 2.0
    base_bars: int = 10
    base_width_atr: float = 2.5
    breakout_volume_ratio: float = 1.2
    min_volume_ratio: float = 1.1
    partial_exit_pct: float = 0.0
    swing_window: int = 3
    min_pattern_quality: float = 40.0
    use_exit_optimizer: bool = False
    use_eth_fix: bool = False
    use_eth_exit_v2: bool = False
    use_btc_exit_final: bool = False
    recovery_position_multiplier: float = 1.0
    eth_reversal_min_pattern_quality: float = 80.0
    eth_reversal_min_setup_score: float = 55.0
    eth_reversal_min_relative_strength: float = 70.0
    eth_reversal_min_volume_ratio: float = 1.5


@dataclass(slots=True)
class CycleTrade:
    entry_date: str
    entry_stage: str
    cycle_state: str
    swing_trend: str
    pattern: str
    pattern_quality: float
    setup_score: float
    position_fraction: float
    leverage: float
    notional: float
    entry_slippage_pct: float
    liquidation_price: float
    funding_cost_pct: float
    entry_price: float
    initial_stop: float
    exit_date: str
    exit_price: float
    return_pct: float
    bars_held: int
    exit_reason: str
    max_favorable_excursion_pct: float
    max_adverse_excursion_pct: float


@dataclass(slots=True)
class CycleBacktestResult:
    strategy_return_pct: float
    buy_and_hold_return_pct: float
    trade_count: int
    win_rate_pct: float
    profit_factor: float
    max_drawdown_pct: float
    exposure_pct: float
    stage_counts: dict[str, int]
    pattern_counts: dict[str, int]
    alignment_counts: dict[str, int]
    state_counts: dict[str, int]
    quality_counts: dict[str, int]
    total_funding_cost_pct: float
    total_slippage_pct: float
    liquidation_count: int
    risk_metrics: RiskMetrics = field(default_factory=RiskMetrics)
    daily_returns: list[dict[str, str | float]] = field(default_factory=list)
    position_flags: list[dict[str, str | bool]] = field(default_factory=list)
    walk_forward: list[dict[str, Any]] = field(default_factory=list)
    trades: list[CycleTrade] = field(default_factory=list)
    open_position: dict[str, Any] | None = None
    equity_curve: list[dict[str, float | str]] = field(default_factory=list)


def prepare_cycle_frame(
    frame: pd.DataFrame,
    config: CycleConfig | None = None,
    intraday_frame: pd.DataFrame | None = None,
    benchmark_frame: pd.DataFrame | None = None,
    symbol: str | None = None,
) -> pd.DataFrame:
    """Add cycle context, chart patterns, and multi-timeframe structure."""
    config = config or CycleConfig()
    df = frame.copy()
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)

    numeric_cols = ["open", "high", "low", "close", "volume"]
    df[numeric_cols] = df[numeric_cols].astype(float)
    df["ema20"] = df["close"].ewm(span=20, adjust=False).mean()
    df["ema50"] = df["close"].ewm(span=50, adjust=False).mean()
    df["ema200"] = df["close"].ewm(span=200, adjust=False).mean()
    df["ema10"] = df["close"].ewm(span=10, adjust=False).mean()
    df["sma50"] = df["close"].rolling(50).mean()
    df["sma200"] = df["close"].rolling(200).mean()
    df["atr20"] = _true_range(df).rolling(20).mean()
    df["volume_ma20"] = df["volume"].rolling(20).mean()
    df["volume_ratio"] = df["volume"] / df["volume_ma20"].replace(0, np.nan)
    df["rsi14"] = _rsi(df["close"], 14)
    df["ema20_slope5"] = df["ema20"].pct_change(5) * 100
    df["ema50_slope5"] = df["ema50"].pct_change(5) * 100
    df["distance_ema20_atr"] = (df["close"] - df["ema20"]) / df["atr20"].replace(0, np.nan)

    _add_weekly_trend(df)
    _add_relative_strength(df, benchmark_frame)
    _add_daily_trend(df, config)
    _add_intraday_trend(df, intraday_frame)
    _detect_patterns(df, config)
    _classify_stages(df, config)
    _add_cycle_state(df)
    _add_alignment(df)
    _add_pattern_quality(df, config)
    _add_setup_signal(df, config, symbol)
    return df


def backtest_cycle(
    frame: pd.DataFrame,
    start_date: str,
    end_date: str,
    config: CycleConfig | None = None,
    intraday_frame: pd.DataFrame | None = None,
    benchmark_frame: pd.DataFrame | None = None,
    symbol: str | None = None,
) -> CycleBacktestResult:
    config = config or CycleConfig()
    data = prepare_cycle_frame(frame, config, intraday_frame, benchmark_frame, symbol)
    start = pd.to_datetime(start_date)
    end = pd.to_datetime(end_date)
    period = data[(data["date"] >= start) & (data["date"] <= end)].reset_index(drop=True)
    if period.empty:
        raise ValueError("No candles in the requested date range.")

    cash = 1.0
    position_qty = 0.0
    entry_stage = ""
    entry_cycle_state = ""
    entry_swing_trend = ""
    entry_pattern = ""
    entry_pattern_quality = 0.0
    entry_setup_score = 0.0
    entry_position_fraction = 0.0
    entry_leverage = config.leverage
    entry_notional = 0.0
    entry_price = 0.0
    entry_slippage_pct = 0.0
    liquidation_price = 0.0
    entry_date = ""
    initial_stop = 0.0
    active_stop = 0.0
    funding_paid = 0.0
    total_funding_paid = 0.0
    total_slippage_paid = 0.0
    max_favorable_excursion_pct = 0.0
    max_adverse_excursion_pct = 0.0
    liquidation_count = 0
    bars_held = 0
    position_days = 0
    closed_this_bar = False
    trades: list[CycleTrade] = []
    equity_curve: list[dict[str, float | str]] = []
    position_flags: list[dict[str, str | bool]] = []
    highest_since_entry = 0.0
    entry_atr = 0.0
    entry_swing_low = 0.0
    phase_stop_atr = PHASE_STOP_ATR
    phase_trail_atr = PHASE_TRAIL_ATR
    asset_profile = (
        ASSET_PROFILES.get(symbol.upper(), {})
        if symbol and config.use_asset_profile
        else {}
    )
    if asset_profile:
        phase_stop_atr = {
            **PHASE_STOP_ATR,
            **asset_profile.get("phase_stop_atr", {}),
        }
        phase_trail_atr = {
            **PHASE_TRAIL_ATR,
            **asset_profile.get("phase_trail_atr", {}),
        }
    elif not config.use_asset_profile:
        phase_stop_atr = {
            stage: config.stop_atr_multiple for stage in PHASE_STOP_ATR
        }
        phase_trail_atr = {
            stage: config.trail_atr_multiple for stage in PHASE_TRAIL_ATR
        }
    exit_optimizer: ExitOptimizer | None = None
    if config.use_exit_optimizer:
        exit_optimizer = (
            create_btc_exit_optimizer()
            if symbol == "BTCUSDT"
            else create_eth_exit_optimizer()
        )
    eth_fix_manager: ETHFixManager | None = None
    if config.use_eth_fix and symbol == "ETHUSDT":
        eth_fix_manager = ETHFixManager(
            ETHFixConfig(
                reversal_min_pattern_quality=config.eth_reversal_min_pattern_quality,
                reversal_min_setup_score=config.eth_reversal_min_setup_score,
                reversal_min_relative_strength=config.eth_reversal_min_relative_strength,
                reversal_min_volume_ratio=config.eth_reversal_min_volume_ratio,
            )
        )
    eth_exit_v2: ETHExitV2 | None = None
    if config.use_eth_exit_v2 and symbol == "ETHUSDT":
        eth_exit_v2 = ETHExitV2()
    btc_exit_final: BTCExitFinal | None = None
    if config.use_btc_exit_final and symbol == "BTCUSDT":
        btc_exit_final = BTCExitFinal()

    def close_position(
        qty: float,
        raw_price: float,
        exit_reason: str,
        exit_date: str,
        liquidated: bool = False,
    ) -> None:
        nonlocal cash, position_qty, bars_held, closed_this_bar
        nonlocal total_funding_paid, total_slippage_paid, liquidation_count

        qty = min(qty, position_qty)
        if qty <= 1e-12:
            return
        exit_price = raw_price if liquidated else raw_price * (1 - config.slippage_rate)
        exit_notional = qty * exit_price
        pnl = qty * (exit_price - entry_price)
        exit_fee = exit_notional * config.fee_rate
        entry_fee = entry_notional * config.fee_rate
        cash += pnl - exit_fee - entry_fee
        if liquidated:
            liquidation_count += 1
            cash = max(cash, 0.0)
        slippage_cost = entry_notional * config.slippage_rate + exit_notional * config.slippage_rate
        total_slippage_paid += slippage_cost
        trade_return = (pnl - entry_fee - exit_fee - funding_paid) / entry_notional * 100
        trades.append(
            CycleTrade(
                entry_date=entry_date,
                entry_stage=entry_stage,
                cycle_state=entry_cycle_state,
                swing_trend=entry_swing_trend,
                pattern=entry_pattern,
                pattern_quality=entry_pattern_quality,
                setup_score=entry_setup_score,
                position_fraction=entry_position_fraction,
                leverage=entry_leverage,
                notional=entry_notional,
                entry_slippage_pct=entry_slippage_pct,
                liquidation_price=liquidation_price,
                funding_cost_pct=funding_paid / entry_notional * 100,
                entry_price=entry_price,
                initial_stop=initial_stop,
                exit_date=exit_date,
                exit_price=exit_price,
                return_pct=trade_return,
                bars_held=bars_held,
                exit_reason=exit_reason,
                max_favorable_excursion_pct=max_favorable_excursion_pct * 100,
                max_adverse_excursion_pct=max_adverse_excursion_pct * 100,
            )
        )
        position_qty = 0.0
        bars_held = 0
        closed_this_bar = True

    def enter_position(row: pd.Series, previous: pd.Series) -> None:
        nonlocal cash, position_qty, entry_stage, entry_cycle_state, entry_swing_trend
        nonlocal entry_pattern, entry_pattern_quality, entry_setup_score, entry_position_fraction
        nonlocal entry_leverage, entry_notional, entry_price, entry_slippage_pct, liquidation_price
        nonlocal entry_date, initial_stop, active_stop, funding_paid, bars_held, position_days
        nonlocal max_favorable_excursion_pct, max_adverse_excursion_pct

        stage = str(previous["stage"])
        setup_score = float(previous["setup_score"])
        if eth_fix_manager is not None:
            allowed, eth_multiplier, reason = eth_fix_manager.should_enter(
                stage=stage,
                pattern=str(previous["pattern"]),
                setup_score=setup_score,
                pattern_quality=float(previous["pattern_quality"]),
                relative_strength=float(previous["relative_strength_score"]),
                volume_ratio=float(previous["volume_ratio"]),
            )
            if not allowed:
                return
        quality_scale = 0.6 + 0.4 * (setup_score / 100)
        raw_fraction = PHASE_POSITION_FRACTION.get(stage, 0.5) * quality_scale
        if stage == "recovery":
            raw_fraction *= config.recovery_position_multiplier
        stop_atr = phase_stop_atr.get(stage, config.stop_atr_multiple)
        stop_distance = stop_atr * float(previous["atr20"]) / float(row["open"])
        risk_fraction = config.risk_per_trade / max(stop_distance * config.leverage, 1e-9)
        position_fraction = min(
            raw_fraction,
            risk_fraction,
            config.max_position_fraction,
        )
        price = float(row["open"]) * (1 + config.slippage_rate)
        notional = cash * position_fraction * config.leverage
        if notional <= 0 or price <= 0:
            return
        entry_fee = notional * config.fee_rate
        cash -= entry_fee
        position_qty = notional / price
        entry_stage = stage
        entry_cycle_state = str(previous["cycle_state"])
        entry_swing_trend = str(previous["swing_trend"])
        entry_pattern = str(previous["pattern"])
        entry_pattern_quality = float(previous["pattern_quality"])
        entry_setup_score = setup_score
        entry_position_fraction = position_fraction
        entry_leverage = config.leverage
        entry_notional = notional
        entry_price = price
        entry_slippage_pct = config.slippage_rate * 100
        liquidation_price = price * max(
            0.0,
            1 - (1 / config.leverage - config.maintenance_margin_rate),
        )
        entry_date = str(previous["date"].date())
        initial_stop = price - stop_atr * float(previous["atr20"])
        active_stop = initial_stop
        entry_atr = float(previous["atr20"])
        entry_swing_low = float(previous.get("last_swing_low", price * 0.95))
        highest_since_entry = price
        if exit_optimizer is not None:
            exit_optimizer.reset()
        if eth_exit_v2 is not None:
            eth_exit_v2.reset()
        if btc_exit_final is not None:
            btc_exit_final.reset()
            initial_stop = price - btc_exit_final.config.loss_hard_stop_atr * entry_atr
            active_stop = initial_stop
        funding_paid = 0.0
        bars_held = 0
        position_days += 1
        max_favorable_excursion_pct = 0.0
        max_adverse_excursion_pct = 0.0

    def update_excursions(row: pd.Series) -> None:
        nonlocal max_favorable_excursion_pct, max_adverse_excursion_pct
        if position_qty <= 1e-12:
            return
        high = float(row["high"])
        low = float(row["low"])
        max_favorable_excursion_pct = max(
            max_favorable_excursion_pct,
            (high - entry_price) / entry_price,
        )
        max_adverse_excursion_pct = min(
            max_adverse_excursion_pct,
            (low - entry_price) / entry_price,
        )

    for i, row in period.iterrows():
        closed_this_bar = False
        price = float(row["open"])

        if position_qty > 1e-12:
            update_excursions(row)
            position_days += 1
            bars_held += 1
            highest_since_entry = max(highest_since_entry, float(row["high"]))
            funding_cost = position_qty * float(row["close"]) * (
                config.funding_rate_annual / 365
            )
            cash -= funding_cost
            funding_paid += funding_cost
            total_funding_paid += funding_cost

            if row["low"] <= liquidation_price:
                close_position(
                    position_qty,
                    liquidation_price,
                    "liquidation",
                    str(row["date"].date()),
                    liquidated=True,
                )
            elif row["low"] <= active_stop:
                close_position(
                    position_qty,
                    min(price, active_stop),
                    "stop_loss",
                    str(row["date"].date()),
                )

        if position_qty <= 1e-12 and i > 0 and not closed_this_bar:
            previous = period.iloc[i - 1]
            if bool(previous["entry_ready"]):
                enter_position(row, previous)

        if (
            position_qty > 1e-12
            and i > 0
            and not closed_this_bar
            and eth_exit_v2 is None
            and btc_exit_final is None
        ):
            previous = period.iloc[i - 1]
            stage = str(previous["stage"])
            if stage == "exhaustion_extension":
                close_position(
                    position_qty * config.partial_exit_pct,
                    price,
                    "exhaustion_partial_exit",
                    str(row["date"].date()),
                )
                active_stop = max(active_stop, entry_price)
            elif stage == "wedge_drop":
                close_position(
                    position_qty,
                    price,
                    "wedge_drop",
                    str(row["date"].date()),
                )

        if (
            position_qty > 1e-12
            and exit_optimizer is not None
            and not closed_this_bar
        ):
            should_exit, reason, exit_pct = exit_optimizer.should_exit(
                {
                    "entry_price": entry_price,
                    "entry_atr": entry_atr,
                    "highest_since_entry": highest_since_entry,
                    "holding_days": bars_held,
                    "entry_swing_low": entry_swing_low,
                },
                row.to_dict(),
            )
            if should_exit:
                close_position(
                    position_qty * exit_pct,
                    float(row["close"]),
                    reason,
                    str(row["date"].date()),
                )

        if (
            position_qty > 1e-12
            and eth_exit_v2 is not None
            and not closed_this_bar
        ):
            should_exit, reason, exit_pct = eth_exit_v2.check_exit(
                {
                    "entry_price": entry_price,
                    "entry_atr": entry_atr,
                    "highest_since_entry": highest_since_entry,
                    "holding_days": bars_held,
                    "entry_swing_low": entry_swing_low,
                },
                row.to_dict(),
            )
            if should_exit:
                close_position(
                    position_qty * exit_pct,
                    float(row["close"]),
                    reason,
                    str(row["date"].date()),
                )

        if (
            position_qty > 1e-12
            and btc_exit_final is not None
            and not closed_this_bar
        ):
            should_exit, reason, exit_pct = btc_exit_final.check_exit(
                {
                    "entry_price": entry_price,
                    "entry_atr": entry_atr,
                    "highest_since_entry": highest_since_entry,
                    "holding_days": bars_held,
                    "entry_swing_low": entry_swing_low,
                },
                row.to_dict(),
                period,
                i,
            )
            if should_exit:
                close_position(
                    position_qty * exit_pct,
                    float(row["close"]),
                    reason,
                    str(row["date"].date()),
                )

        if position_qty > 1e-12:
            update_excursions(row)
            if exit_optimizer is None and eth_exit_v2 is None and btc_exit_final is None:
                trail_atr = phase_trail_atr.get(
                    entry_stage,
                    config.trail_atr_multiple,
                )
                trail_stop = float(row["high"]) - trail_atr * float(row["atr20"])
                active_stop = max(active_stop, trail_stop)

        equity = cash + position_qty * (float(row["close"]) - entry_price)
        was_in_position = position_qty > 1e-12
        equity_curve.append(
            {
                "date": str(row["date"].date()),
                "equity": equity,
            }
        )
        position_flags.append(
            {
                "date": str(row["date"].date()),
                "in_position": was_in_position,
            }
        )

    first_open = float(period.iloc[0]["open"])
    last_close = float(period.iloc[-1]["close"])
    strategy_return = (equity_curve[-1]["equity"] - 1) * 100
    buy_and_hold = (last_close / first_open - 1) * 100

    equity_dates = pd.to_datetime(period["date"])
    equity_values = [point["equity"] for point in equity_curve]
    equity_series = pd.Series(equity_values, index=equity_dates, dtype=float)
    daily_returns = equity_series.pct_change().fillna(0.0)
    daily_return_rows = [
        {"date": date.strftime("%Y-%m-%d"), "return": float(value)}
        for date, value in daily_returns.items()
    ]
    trade_pnl_list = [
        trade.notional * trade.return_pct / 100
        for trade in trades
    ]
    risk_metrics = compute_risk_metrics(
        daily_returns,
        trade_pnl_list=trade_pnl_list,
    )
    drawdown = ((equity_series / equity_series.cummax()) - 1).min() * 100
    wins = sum(trade.return_pct > 0 for trade in trades)
    gross_profit = sum(trade.return_pct for trade in trades if trade.return_pct > 0)
    gross_loss = abs(sum(trade.return_pct for trade in trades if trade.return_pct <= 0))

    open_position = None
    if position_qty > 1e-12:
        open_position = {
            "entry_date": entry_date,
            "entry_stage": entry_stage,
            "cycle_state": entry_cycle_state,
            "pattern": entry_pattern,
            "pattern_quality": entry_pattern_quality,
            "setup_score": entry_setup_score,
            "position_fraction": entry_position_fraction,
            "leverage": entry_leverage,
            "notional": entry_notional,
            "entry_price": entry_price,
            "liquidation_price": liquidation_price,
            "unrealized_pnl": position_qty * (last_close - entry_price),
            "stop": active_stop,
        }

    return CycleBacktestResult(
        strategy_return_pct=round(float(strategy_return), 2),
        buy_and_hold_return_pct=round(float(buy_and_hold), 2),
        trade_count=len(trades),
        win_rate_pct=round(wins / len(trades) * 100, 2) if trades else 0.0,
        profit_factor=round(gross_profit / gross_loss, 2) if gross_loss else 0.0,
        max_drawdown_pct=round(float(drawdown), 2),
        exposure_pct=round(position_days / len(period) * 100, 2),
        stage_counts=dict(Counter(period["stage"])),
        pattern_counts=dict(Counter(period["pattern"])),
        alignment_counts=dict(Counter(period["mtf_alignment"])),
        state_counts=dict(Counter(period["cycle_state"])),
        quality_counts=dict(Counter(period["pattern_grade"])),
        total_funding_cost_pct=round(total_funding_paid * 100, 2),
        total_slippage_pct=round(total_slippage_paid * 100, 2),
        liquidation_count=liquidation_count,
        risk_metrics=risk_metrics,
        daily_returns=daily_return_rows,
        position_flags=position_flags,
        trades=trades,
        open_position=open_position,
        equity_curve=equity_curve,
    )


def walk_forward_cycle(
    frame: pd.DataFrame,
    start_date: str,
    end_date: str,
    config: CycleConfig | None = None,
    intraday_frame: pd.DataFrame | None = None,
    benchmark_frame: pd.DataFrame | None = None,
    train_days: int = 180,
    test_days: int = 90,
    setup_score_candidates: tuple[float, ...] = (50.0, 60.0, 70.0),
    symbol: str | None = None,
) -> list[dict[str, Any]]:
    """Run rolling out-of-sample folds and select the threshold on train data."""
    config = config or CycleConfig()
    start = pd.to_datetime(start_date)
    end = pd.to_datetime(end_date)
    test_start = start
    folds: list[dict[str, Any]] = []

    while test_start <= end:
        test_end = min(test_start + pd.Timedelta(days=test_days - 1), end)
        train_start = test_start - pd.Timedelta(days=train_days)
        train_end = test_start - pd.Timedelta(days=1)
        best_score = -float("inf")
        best_threshold = config.min_setup_score
        best_train_result = None

        for threshold in setup_score_candidates:
            candidate_config = replace(config, min_setup_score=float(threshold))
            try:
                result = backtest_cycle(
                    frame,
                    str(train_start.date()),
                    str(train_end.date()),
                candidate_config,
                intraday_frame,
                benchmark_frame,
                symbol=symbol,
                )
            except ValueError:
                continue
            score = result.strategy_return_pct - abs(result.max_drawdown_pct) * 0.5
            if score > best_score:
                best_score = score
                best_threshold = float(threshold)
                best_train_result = result

        test_config = replace(config, min_setup_score=best_threshold)
        try:
            test_result = backtest_cycle(
                frame,
                str(test_start.date()),
                str(test_end.date()),
            test_config,
            intraday_frame,
            benchmark_frame,
            symbol=symbol,
            )
        except ValueError:
            test_result = None

        if test_result is not None:
            folds.append(
                {
                    "train_start": str(train_start.date()),
                    "train_end": str(train_end.date()),
                    "test_start": str(test_start.date()),
                    "test_end": str(test_end.date()),
                    "selected_min_setup_score": best_threshold,
                    "train_return_pct": best_train_result.strategy_return_pct if best_train_result else 0.0,
                    "train_max_drawdown_pct": best_train_result.max_drawdown_pct if best_train_result else 0.0,
                    "test_return_pct": test_result.strategy_return_pct,
                    "test_max_drawdown_pct": test_result.max_drawdown_pct,
                    "test_trade_count": test_result.trade_count,
                    "test_win_rate_pct": test_result.win_rate_pct,
                    "test_liquidation_count": test_result.liquidation_count,
                }
            )
        test_start = test_end + pd.Timedelta(days=1)

    return folds


def _true_range(frame: pd.DataFrame) -> pd.Series:
    previous_close = frame["close"].shift(1)
    high_low = frame["high"] - frame["low"]
    high_close = (frame["high"] - previous_close).abs()
    low_close = (frame["low"] - previous_close).abs()
    return pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)


def _rsi(closes: pd.Series, period: int) -> pd.Series:
    delta = closes.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - 100 / (1 + rs)


def _add_weekly_trend(df: pd.DataFrame) -> None:
    dates = pd.to_datetime(df["date"])
    week_start = dates - pd.to_timedelta(dates.dt.weekday, unit="D")
    weekly = (
        df.assign(week_start=week_start)
        .groupby("week_start", sort=True)
        .agg(
            open=("open", "first"),
            high=("high", "max"),
            low=("low", "min"),
            close=("close", "last"),
            volume=("volume", "sum"),
        )
        .reset_index()
    )
    weekly["ema20"] = weekly["close"].ewm(span=20, adjust=False).mean()
    weekly["ema50"] = weekly["close"].ewm(span=50, adjust=False).mean()
    weekly["trend"] = np.select(
        [
            (weekly["close"] > weekly["ema20"]) & (weekly["ema20"] > weekly["ema50"]),
            (weekly["close"] < weekly["ema20"]) & (weekly["ema20"] < weekly["ema50"]),
        ],
        ["up", "down"],
        default="range",
    )
    lagged_trend = weekly.set_index("week_start")["trend"].shift(1)
    df["weekly_trend"] = week_start.map(lagged_trend).fillna("range")
    lagged_ema20 = weekly.set_index("week_start")["ema20"].shift(1)
    lagged_ema50 = weekly.set_index("week_start")["ema50"].shift(1)
    df["weekly_ema20"] = week_start.map(lagged_ema20).fillna(0.0)
    df["weekly_ema50"] = week_start.map(lagged_ema50).fillna(0.0)


def _add_swing_points(df: pd.DataFrame, window: int = 3) -> None:
    span = window * 2 + 1
    pivot_high = df["high"] == df["high"].rolling(span, center=True).max()
    pivot_low = df["low"] == df["low"].rolling(span, center=True).min()
    df["pivot_high"] = pivot_high.shift(window, fill_value=False)
    df["pivot_low"] = pivot_low.shift(window, fill_value=False)
    confirmed_high = df["high"].where(df["pivot_high"]).ffill()
    confirmed_low = df["low"].where(df["pivot_low"]).ffill()
    df["last_swing_high"] = confirmed_high
    df["previous_swing_high"] = confirmed_high.shift(1)
    df["last_swing_low"] = confirmed_low
    df["previous_swing_low"] = confirmed_low.shift(1)

    atr = df["atr20"].replace(0, np.nan)
    high_delta = (confirmed_high - confirmed_high.shift(1)) / atr
    low_delta = (confirmed_low - confirmed_low.shift(1)) / atr
    higher_high = high_delta > 0
    higher_low = low_delta > 0
    lower_high = high_delta < 0
    lower_low = low_delta < 0
    df["swing_trend"] = np.select(
        [
            higher_high & higher_low,
            lower_high & lower_low,
        ],
        ["hh_hl", "lh_ll"],
        default="range",
    )
    df["swing_structure_score"] = (
        np.sign(high_delta).fillna(0) + np.sign(low_delta).fillna(0)
    )
    swing_quality = (
        0.5 * (1 + np.tanh(high_delta.fillna(0)))
        + 0.5 * (1 + np.tanh(low_delta.fillna(0)))
    ) * 50
    df["swing_quality"] = swing_quality.clip(0, 100)
    df["last_pivot_high"] = confirmed_high
    df["last_pivot_low"] = confirmed_low


def _add_daily_trend(df: pd.DataFrame, config: CycleConfig) -> None:
    _add_swing_points(df, config.swing_window)
    up = (
        (df["close"] > df["ema20"])
        & (df["ema10"] > df["ema20"])
        & (df["ema20"] > df["ema50"])
        & (df["ema20"] > df["sma50"])
        & (df["sma50"] > df["sma200"])
        & (df["ema20_slope5"] > 0)
    )
    down = (
        (df["close"] < df["ema20"])
        & (df["ema10"] < df["ema20"])
        & (df["ema20"] < df["ema50"])
        & (df["ema20"] < df["sma50"])
        & (df["sma50"] < df["sma200"])
        & (df["ema20_slope5"] < 0)
    )
    df["daily_trend"] = np.select([up, down], ["up", "down"], default="range")
    df["daily_structure"] = df["swing_trend"]
    df["ma_score"] = (
        (df["close"] > df["ema10"]).astype(int) * 15
        + (df["close"] > df["ema20"]).astype(int) * 15
        + (df["ema20"] > df["sma50"]).astype(int) * 25
        + (df["sma50"] > df["sma200"]).astype(int) * 25
        + (df["close"] > df["sma200"]).astype(int) * 20
    )


def _add_relative_strength(df: pd.DataFrame, benchmark_frame: pd.DataFrame | None) -> None:
    if benchmark_frame is None or benchmark_frame.empty:
        df["relative_strength_20"] = 0.0
        df["relative_strength_score"] = 50.0
        return

    benchmark = benchmark_frame[["date", "close"]].copy()
    benchmark["date"] = pd.to_datetime(benchmark["date"])
    benchmark_close = benchmark.drop_duplicates("date").set_index("date")["close"]
    benchmark_close = benchmark_close.astype(float)
    ratio = df["close"] / df["date"].map(benchmark_close).astype(float)
    relative_strength = ratio.pct_change(20) * 100
    percentile = relative_strength.rolling(60, min_periods=10).rank(pct=True) * 100
    df["relative_strength_20"] = relative_strength
    df["relative_strength_score"] = percentile.fillna(50).clip(0, 100)


def _add_intraday_trend(df: pd.DataFrame, intraday_frame: pd.DataFrame | None) -> None:
    if intraday_frame is None or intraday_frame.empty:
        df["intraday_trend"] = "unknown"
        df["intraday_structure"] = "unknown"
        df["intraday_trigger"] = False
        return

    intraday = intraday_frame.copy()
    intraday["date"] = pd.to_datetime(intraday["date"]).dt.date
    intraday["ema20"] = intraday["close"].ewm(span=20, adjust=False).mean()
    intraday["ema50"] = intraday["close"].ewm(span=50, adjust=False).mean()
    intraday_up = (
        (intraday["close"] > intraday["ema20"])
        & (intraday["ema20"] > intraday["ema50"])
        & (intraday["close"] > intraday["open"])
    )
    intraday_down = (
        (intraday["close"] < intraday["ema20"])
        & (intraday["ema20"] < intraday["ema50"])
        & (intraday["close"] < intraday["open"])
    )
    intraday["trend"] = np.select(
        [intraday_up, intraday_down],
        ["up", "down"],
        default="range",
    )
    intraday["structure"] = np.select(
        [
            (intraday["close"] > intraday["ema20"])
            & (intraday["low"] <= intraday["ema20"])
            & (intraday["close"] > intraday["open"]),
            (intraday["close"] < intraday["ema20"])
            & (intraday["high"] >= intraday["ema20"])
            & (intraday["close"] < intraday["open"]),
        ],
        ["pullback_hold", "rally_reject"],
        default="transition",
    )
    intraday["trigger"] = intraday["structure"].eq("pullback_hold")

    daily_key = pd.to_datetime(df["date"]).dt.date
    trend_by_date = intraday.groupby("date", sort=True)["trend"].last()
    structure_by_date = intraday.groupby("date", sort=True)["structure"].last()
    trigger_by_date = intraday.groupby("date", sort=True)["trigger"].max()
    df["intraday_trend"] = daily_key.map(trend_by_date).fillna("unknown")
    df["intraday_structure"] = daily_key.map(structure_by_date).fillna("unknown")
    df["intraday_trigger"] = daily_key.map(trigger_by_date).fillna(False).astype(bool)


def _detect_patterns(df: pd.DataFrame, config: CycleConfig) -> None:
    atr = df["atr20"].replace(0, np.nan)
    range_high = df["high"].rolling(config.base_bars, min_periods=config.base_bars).max().shift(1)
    range_low = df["low"].rolling(config.base_bars, min_periods=config.base_bars).min().shift(1)
    range_width = (range_high - range_low) / atr
    is_base = range_width < config.base_width_atr
    prior_move = df["close"] - df["close"].shift(config.base_bars)
    candle_range = (df["high"] - df["low"]).replace(0, np.nan)
    close_position_in_range = (df["close"] - df["low"]) / candle_range

    capitulation_reversal = (
        (df["low"] < df["ema20"] - config.reversal_atr * atr)
        & (df["volume_ratio"] > 1.5)
        & (df["close"] > df["open"])
        & (close_position_in_range > 0.6)
    )
    flat_base_breakout = (
        is_base
        & (df["close"] > range_high)
        & (df["volume_ratio"] > config.breakout_volume_ratio)
    )
    bull_flag_breakout = (
        is_base
        & (prior_move > config.reversal_atr * atr)
        & (df["close"] > range_high)
        & (df["volume_ratio"] > config.breakout_volume_ratio)
    )
    higher_low_reclaim = (
        (df["low"] > df["last_pivot_low"])
        & (df["close"] > df["ema20"])
        & (df["close"].shift(1) < df["ema20"].shift(1))
    )
    prior_low = df["low"].rolling(config.base_bars, min_periods=config.base_bars).min().shift(config.base_bars)
    current_low = df["low"].rolling(config.base_bars, min_periods=config.base_bars).min()
    double_bottom = (
        ((prior_low - current_low).abs() < atr * 0.8)
        & (df["close"] > range_high)
        & (df["volume_ratio"] > config.breakout_volume_ratio)
    )

    conditions = [
        capitulation_reversal,
        flat_base_breakout,
        bull_flag_breakout,
        double_bottom,
        higher_low_reclaim,
    ]
    names = [
        "capitulation_reversal",
        "flat_base_breakout",
        "bull_flag_breakout",
        "double_bottom_breakout",
        "higher_low_reclaim",
    ]
    df["pattern"] = np.select(conditions, names, default="none")
    df["pattern_score"] = sum(condition.astype(int) for condition in conditions)


def _add_alignment(df: pd.DataFrame) -> None:
    weekly_up = df["weekly_trend"].eq("up")
    daily_up = df["daily_trend"].eq("up")
    intraday_up = df["intraday_trend"].eq("up")
    df["mtf_alignment"] = np.select(
        [
            weekly_up & daily_up & intraday_up,
            weekly_up & daily_up,
            daily_up,
        ],
        ["full", "weekly_daily", "daily_only"],
        default="none",
    )


def _add_setup_signal(
    df: pd.DataFrame,
    config: CycleConfig,
    symbol: str | None = None,
) -> None:
    state_health = (
        0.60 * df["quality_cycle"]
        + 0.20 * df["ma_score"]
        + 0.10 * df["relative_strength_score"]
        + 0.10 * df["stage_sequence_valid"].astype(float) * 100
    )
    setup_score = (
        0.35 * df["pattern_quality"]
        + 0.20 * state_health
        + 0.20 * df["quality_swing"]
        + 0.15 * df["quality_trend"]
        + 0.10 * df["relative_strength_score"]
    ).clip(0, 100)

    stage = df["stage"]
    execution_mode = config.execution_mode.lower()
    trigger_ready = (
        df["intraday_trigger"] if execution_mode == "4h" else pd.Series(True, index=df.index)
    )
    is_reversal = stage.eq("reversal_extension")
    is_continuation = stage.isin(["wedge_pop", "ema_crossback", "base_n_break"])
    asset_profile = ASSET_PROFILES.get(symbol.upper(), {}) if symbol else {}
    relaxed_reversal = asset_profile.get("relaxed_reversal", {})
    reversal_ready = (
        is_reversal
        & df["pattern"].eq("capitulation_reversal")
        & (df["pattern_quality"] >= config.min_pattern_quality)
        & (setup_score >= config.min_setup_score - 10)
        & df["weekly_trend"].ne("down")
        & trigger_ready
    )
    high_quality_reversal_ready = (
        is_reversal
        & df["pattern"].eq("capitulation_reversal")
        & (
            df["pattern_quality"]
            >= relaxed_reversal.get("pattern_quality", float("inf"))
        )
        & (
            setup_score
            >= relaxed_reversal.get("setup_score", float("inf"))
        )
        & df["weekly_trend"].ne("down")
        & (df["relative_strength_score"] >= 60)
        & trigger_ready
    )
    continuation_ready = (
        is_continuation
        & df["pattern"].ne("none")
        & (df["pattern_quality"] >= config.min_pattern_quality)
        & (setup_score >= config.min_setup_score - 10)
        & trigger_ready
    )

    df["setup_score"] = setup_score.round(1)
    df["state_health"] = state_health.clip(0, 100).round(1)
    df["entry_ready"] = (
        high_quality_reversal_ready
        | reversal_ready
        | continuation_ready
    )


def _classify_stages(df: pd.DataFrame, config: CycleConfig) -> None:
    previous_close = df["close"].shift(1)
    previous_ema20 = df["ema20"].shift(1)
    previous_ema50 = df["ema50"].shift(1)
    previous_high = df["high"].shift(1)
    range_high = df["high"].rolling(config.base_bars, min_periods=config.base_bars).max().shift(1)
    range_low = df["low"].rolling(config.base_bars, min_periods=config.base_bars).min().shift(1)
    range_width = (range_high - range_low) / df["atr20"].replace(0, np.nan)
    is_base = range_width < config.base_width_atr
    candle_range = (df["high"] - df["low"]).replace(0, np.nan)
    close_position_in_range = (df["close"] - df["low"]) / candle_range

    reversal_extension = (
        (df["close"] < df["ema50"])
        & (df["low"] < df["ema20"] - config.reversal_atr * df["atr20"])
        & (df["volume_ratio"] > 1.5)
        & (df["close"] > df["open"])
        & (close_position_in_range > 0.6)
    )
    wedge_pop = (
        (previous_close < previous_ema20)
        & (df["close"] > df["ema20"])
        & (df["close"] > previous_high)
        & (df["volume_ratio"] > config.min_volume_ratio)
        & (df["ema20_slope5"] > 0)
    )
    ema_crossback = (
        (previous_close < previous_ema20)
        & (df["close"] > df["ema20"])
        & (df["ema20_slope5"] > -0.25)
    )
    base_n_break = (
        is_base
        & (df["close"] > range_high)
        & (df["volume_ratio"] > config.breakout_volume_ratio)
        & (df["ema20"] > df["ema50"])
    )
    wedge_drop = (
        (df["close"] < df["ema50"])
        & (previous_close >= previous_ema50)
        & (df["ema20_slope5"] < 0)
        & (df["volume_ratio"] > config.min_volume_ratio)
    )
    ema_crossback_downside = (
        (previous_close > previous_ema20)
        & (df["close"] < df["ema20"])
        & (df["ema20"] < df["ema50"])
    )
    base_n_break_downside = (
        is_base
        & (df["close"] < range_low)
        & (df["volume_ratio"] > config.breakout_volume_ratio)
        & (df["ema20"] < df["ema50"])
    )
    exhaustion_extension = (
        (df["distance_ema20_atr"] > config.exhaustion_atr)
        & (df["rsi14"] > 70)
        & (df["volume_ratio"] > config.min_volume_ratio)
    )

    df["stage"] = np.select(
        [
            reversal_extension,
            wedge_pop,
            base_n_break,
            ema_crossback,
            wedge_drop,
            base_n_break_downside,
            ema_crossback_downside,
            exhaustion_extension,
        ],
        [
            "reversal_extension",
            "wedge_pop",
            "base_n_break",
            "ema_crossback",
            "wedge_drop",
            "base_n_break_downside",
            "ema_crossback_downside",
            "exhaustion_extension",
        ],
        default="transition",
    )


def _add_cycle_state(df: pd.DataFrame) -> None:
    states: list[str] = []
    transitions: list[str] = []
    sequence_valid: list[bool] = []
    ages: list[int] = []

    current = "unknown"
    age = 0
    for stage, close, ema20, ema50 in zip(
        df["stage"], df["close"], df["ema20"], df["ema50"]
    ):
        stage_name = str(stage)
        target = STAGE_STATE_MAP.get(stage_name, current)

        if target == current:
            new_state = current
            valid = True
            age += 1
        else:
            allowed = CYCLE_NEXT_STATES.get(current, set(CYCLE_STATES))
            if target in allowed:
                new_state = target
                valid = True
                age = 1
            elif (
                current in {"accumulation", "recovery", "markup"}
                and close < ema20 < ema50
            ):
                new_state = "markdown"
                valid = True
                age = 1
            elif current in {"distribution", "markdown"} and close > ema20 > ema50:
                new_state = "recovery"
                valid = True
                age = 1
            else:
                new_state = current
                valid = False
                age += 1

        states.append(new_state)
        transitions.append(f"{current}->{new_state}")
        sequence_valid.append(valid)
        ages.append(age)
        current = new_state

    state_rank = {name: index for index, name in enumerate(CYCLE_STATES)}
    df["cycle_state"] = states
    df["cycle_state_transition"] = transitions
    df["stage_sequence_valid"] = sequence_valid
    df["cycle_state_age"] = ages
    df["cycle_position"] = df["cycle_state"].map(state_rank)


def _add_pattern_quality(df: pd.DataFrame, config: CycleConfig) -> None:
    atr = df["atr20"].replace(0, np.nan)
    range_high = df["high"].rolling(config.base_bars, min_periods=config.base_bars).max().shift(1)
    range_low = df["low"].rolling(config.base_bars, min_periods=config.base_bars).min().shift(1)
    range_width = ((range_high - range_low) / atr).fillna(config.base_width_atr)
    tightness = (1 - (range_width / config.base_width_atr).clip(0, 1)) * 100
    volume = ((df["volume_ratio"] - 1).clip(0, 1)) * 100
    candle_range = (df["high"] - df["low"]).replace(0, np.nan)
    close_position = ((df["close"] - df["low"]) / candle_range).fillna(0) * 100
    alignment_score = df["mtf_alignment"].map(
        {"full": 100.0, "weekly_daily": 70.0, "daily_only": 40.0}
    ).fillna(0.0)
    trend_score = (
        0.45 * df["ma_score"]
        + 0.35 * alignment_score
        + 0.20 * df["relative_strength_score"]
    ).astype(float)
    state_score = (
        df["cycle_state"]
        .map(
            {
                "accumulation": 55.0,
                "recovery": 80.0,
                "markup": 100.0,
                "distribution": 20.0,
                "markdown": 0.0,
                "unknown": 0.0,
            }
        )
        .fillna(0.0)
    )
    state_score = (
        0.80 * state_score
        + 0.20 * df["stage_sequence_valid"].astype(float) * 100
    )
    trigger = pd.Series(np.where(df["intraday_trigger"], 100.0, 0.0), index=df.index)
    structure_score = (
        0.70 * df["swing_quality"]
        + 0.30 * ((df["swing_structure_score"] + 2) / 4 * 100)
    ).clip(0, 100)

    df["quality_tightness"] = tightness.clip(0, 100)
    df["quality_volume"] = volume.clip(0, 100)
    df["quality_trend"] = trend_score.clip(0, 100)
    df["quality_cycle"] = state_score.clip(0, 100)
    df["quality_swing"] = structure_score.clip(0, 100)
    df["quality_trigger"] = np.clip(trigger, 0, 100)

    quality = pd.Series(0.0, index=df.index)
    is_capitulation = df["pattern"].eq("capitulation_reversal")
    is_base_break = df["pattern"].isin(
        ["flat_base_breakout", "bull_flag_breakout", "double_bottom_breakout"]
    )
    is_reclaim = df["pattern"].eq("higher_low_reclaim")

    quality.loc[is_capitulation] = (
        0.35 * volume.loc[is_capitulation]
        + 0.30 * close_position.loc[is_capitulation]
        + 0.20 * df.loc[is_capitulation, "swing_quality"]
        + 0.15 * state_score.loc[is_capitulation]
    )
    quality.loc[is_base_break] = (
        0.30 * tightness.loc[is_base_break]
        + 0.25 * volume.loc[is_base_break]
        + 0.20 * trend_score.loc[is_base_break]
        + 0.15 * state_score.loc[is_base_break]
        + 0.10 * structure_score.loc[is_base_break]
    )
    quality.loc[is_reclaim] = (
        0.30 * df.loc[is_reclaim, "swing_quality"]
        + 0.25 * volume.loc[is_reclaim]
        + 0.20 * trend_score.loc[is_reclaim]
        + 0.15 * state_score.loc[is_reclaim]
        + 0.10 * trigger
    )

    df["pattern_quality"] = quality.clip(0, 100).round(1)
    df["pattern_grade"] = np.select(
        [
            df["pattern_quality"] >= 80,
            df["pattern_quality"] >= 65,
            df["pattern_quality"] >= 50,
            df["pattern_quality"] >= 35,
        ],
        ["A", "B", "C", "D"],
        default="F",
    )
