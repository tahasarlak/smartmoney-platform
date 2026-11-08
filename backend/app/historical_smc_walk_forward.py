from __future__ import annotations

import math
from typing import Any

from .historical_signal_engine import generate_historical_smc_signals
from .strategy_validation import validate_strategy_walk_forward


def run_historical_smc_walk_forward(
    candles_by_symbol_and_tf: dict[str, dict[str, list[dict[str, Any]]]],
    *,
    initial_equity: float = 10_000.0,
    risk_percent: float = 0.5,
    min_quality_score: int = 65,
    min_rr: float = 2.0,
    allow_counter_trend: bool = False,
    max_signals_per_symbol: int = 500,
    history_limit: int = 500,
    spread: float = 0.0,
    slippage: float = 0.0,
    commission_pct: float = 0.0,
    max_open_trades: int = 3,
    max_daily_loss_pct: float = 3.0,
    max_weekly_loss_pct: float = 6.0,
    max_drawdown_pct: float = 15.0,
    folds: int = 4,
    monte_carlo_simulations: int = 1000,
    random_seed: int = 42,
    stress_cost_multiplier: float = 2.0,
) -> dict[str, Any]:
    """Causal SMC signal generation followed by chronological OOS validation.

    The signal engine evaluates each historical decision using only fully
    closed candles available at that decision. The validator then evaluates
    signals whose decision timestamps fall inside each later OOS fold.

    This is a fixed-rule temporal validation, not parameter optimization:
    no model is fitted on the training window. Results remain research-only.
    """
    if not isinstance(candles_by_symbol_and_tf, dict) or not candles_by_symbol_and_tf:
        raise ValueError("candles_by_symbol_and_tf must not be empty")
    if len(candles_by_symbol_and_tf) > 30:
        raise ValueError("Maximum 30 symbols are supported")
    try:
        initial_equity = float(initial_equity)
        risk_percent = float(risk_percent)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("initial_equity and risk_percent must be numeric") from exc
    if not math.isfinite(initial_equity) or initial_equity <= 0:
        raise ValueError("initial_equity must be finite and positive")
    if not math.isfinite(risk_percent) or not 0 < risk_percent <= 2:
        raise ValueError("risk_percent must be greater than 0 and at most 2")

    candles_by_symbol: dict[str, list[dict[str, Any]]] = {}
    generated_by_symbol: dict[str, Any] = {}
    signals: list[dict[str, Any]] = []

    for raw_symbol, timeframe_data in candles_by_symbol_and_tf.items():
        symbol = str(raw_symbol).strip().upper()
        if not symbol or len(symbol) > 30 or symbol in candles_by_symbol:
            raise ValueError(f"Invalid or duplicate symbol: {raw_symbol}")
        if not isinstance(timeframe_data, dict) or "5m" not in timeframe_data:
            raise ValueError(f"Missing timeframe data or 5m candles for {symbol}")

        generated = generate_historical_smc_signals(
            symbol,
            timeframe_data,
            min_quality_score=min_quality_score,
            min_rr=min_rr,
            risk_percent=risk_percent,
            allow_counter_trend=allow_counter_trend,
            max_signals=max_signals_per_symbol,
            history_limit=history_limit,
        )
        if generated.get("status") != "completed":
            raise ValueError(f"Historical signal generation failed for {symbol}")

        five_minute = timeframe_data["5m"]
        candles_by_symbol[symbol] = five_minute
        generated_by_symbol[symbol] = generated

        for raw_signal in generated.get("signals", []):
            signal = dict(raw_signal)
            if signal.get("execution_allowed") is not False:
                raise ValueError("Historical research signals must not allow execution")
            try:
                index = int(signal["index"])
                direction = str(signal["direction"]).lower()
                entry_reference = float(signal["entry_reference"])
                stop = float(signal["stop_loss"])
                target = float(signal["take_profit"])
            except (KeyError, TypeError, ValueError, OverflowError) as exc:
                raise ValueError(f"Invalid generated signal for {symbol}") from exc
            if index < 0 or index >= len(five_minute) - 1:
                raise ValueError(f"Signal index for {symbol} has no following candle")
            if direction not in ("bullish", "bearish"):
                raise ValueError(f"Invalid direction for {symbol}")
            if not all(math.isfinite(v) and v > 0 for v in (entry_reference, stop, target)):
                raise ValueError(f"Invalid signal prices for {symbol}")
            risk_distance = entry_reference - stop if direction == "bullish" else stop - entry_reference
            reward_distance = target - entry_reference if direction == "bullish" else entry_reference - target
            if risk_distance <= 0 or reward_distance <= 0:
                raise ValueError(f"Invalid stop/target geometry for {symbol}")

            signal["quantity"] = (initial_equity * risk_percent / 100.0) / risk_distance
            signal["symbol"] = symbol
            signals.append(signal)

    signals.sort(
        key=lambda item: (
            int(candles_by_symbol[item["symbol"]][int(item["index"])]["time"]),
            item["symbol"],
            int(item["index"]),
        )
    )

    validation = validate_strategy_walk_forward(
        candles_by_symbol,
        signals,
        initial_equity=initial_equity,
        spread=spread,
        slippage=slippage,
        commission_pct=commission_pct,
        max_open_trades=max_open_trades,
        max_daily_loss_pct=max_daily_loss_pct,
        max_weekly_loss_pct=max_weekly_loss_pct,
        max_drawdown_pct=max_drawdown_pct,
        folds=folds,
        monte_carlo_simulations=monte_carlo_simulations,
        random_seed=random_seed,
        stress_cost_multiplier=stress_cost_multiplier,
    )

    return {
        **validation,
        "signal_source": "historical_smc_engine",
        "methodology_version": "historical-smc-walk-forward-1.0",
        "generated_signal_count": len(signals),
        "generated_signals_by_symbol": {
            symbol: result["signal_count"] for symbol, result in generated_by_symbol.items()
        },
        "signal_generation": generated_by_symbol,
        "position_sizing": {
            "method": "fixed_initial_equity_risk_budget",
            "risk_percent_per_signal": risk_percent,
            "quantity_basis": "signal_entry_reference_to_stop_distance",
            "warning": (
                "Quantity uses initial equity and reference entry. Actual next-open "
                "fills, gaps, costs and concurrent positions can change realized risk."
            ),
        },
        "validation_design": {
            "type": "chronological_rolling_out_of_sample",
            "folds": folds,
            "signal_generation": "causal_prefix_per_decision",
            "training_behavior": (
                "Fixed strategy rules; no fitting or parameter optimization is performed "
                "inside training windows."
            ),
            "execution_allowed": False,
        },
        "execution_allowed": False,
    }
