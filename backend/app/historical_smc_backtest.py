from __future__ import annotations

import math
from typing import Any

from .historical_signal_engine import generate_historical_smc_signals
from .multi_backtesting import run_multi_symbol_backtest


def run_historical_smc_portfolio_backtest(
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
    use_regime_filter: bool = False,
    reject_transition_regime: bool = True,
    require_trend_alignment: bool = True,
    reject_high_volatility: bool = False,
    signal_time_start: int | None = None,
    signal_time_end: int | None = None,
) -> dict[str, Any]:
    """Generate causal SMC signals per symbol and replay them in one portfolio.

    Position quantity is fixed per signal from initial equity and the signal's
    reference entry-to-stop distance. Actual fills occur at the next 5m open;
    therefore a gap can make realized risk differ from the requested risk.
    This is a research backtest only and never enables order execution.
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

    if signal_time_start is not None and signal_time_end is not None and signal_time_end <= signal_time_start:
        raise ValueError("signal_time_end must be greater than signal_time_start")

    normalized: dict[str, dict[str, list[dict[str, Any]]]] = {}
    candles_5m: dict[str, list[dict[str, Any]]] = {}
    generated: dict[str, Any] = {}
    all_signals: list[dict[str, Any]] = []

    for raw_symbol, tf_data in candles_by_symbol_and_tf.items():
        symbol = str(raw_symbol).strip().upper()
        if not symbol or len(symbol) > 30 or symbol in normalized:
            raise ValueError(f"Invalid or duplicate symbol: {raw_symbol}")
        if not isinstance(tf_data, dict):
            raise ValueError(f"Timeframe data for {symbol} must be a dictionary")
        if "5m" not in tf_data or not isinstance(tf_data["5m"], list):
            raise ValueError(f"Missing 5m candles for {symbol}")

        result = generate_historical_smc_signals(
            symbol,
            tf_data,
            min_quality_score=min_quality_score,
            min_rr=min_rr,
            risk_percent=risk_percent,
            allow_counter_trend=allow_counter_trend,
            max_signals=max_signals_per_symbol,
            history_limit=history_limit,
            use_regime_filter=use_regime_filter,
            reject_transition_regime=reject_transition_regime,
            require_trend_alignment=require_trend_alignment,
            reject_high_volatility=reject_high_volatility,
        )
        if result.get("status") != "completed":
            raise ValueError(f"Historical signal generation failed for {symbol}")

        rows_5m = tf_data["5m"]
        replay_rows = (
            [row for row in rows_5m if int(row["time"]) < signal_time_end]
            if signal_time_end is not None else rows_5m
        )
        if len(replay_rows) < 2:
            raise ValueError(f"Insufficient 5m candles inside replay window for {symbol}")
        candles_5m[symbol] = replay_rows
        normalized[symbol] = tf_data
        generated[symbol] = result

        for raw_signal in result.get("signals", []):
            signal_time = int(raw_signal.get("signal_time", -1))
            if signal_time_start is not None and signal_time < signal_time_start:
                continue
            if signal_time_end is not None and signal_time >= signal_time_end:
                continue
            signal = dict(raw_signal)
            if signal.get("execution_allowed") is not False:
                raise ValueError("Historical research signals must not allow execution")
            try:
                entry_reference = float(signal["entry_reference"])
                stop = float(signal["stop_loss"])
                direction = str(signal["direction"]).lower()
                idx = int(signal["index"])
            except (KeyError, TypeError, ValueError, OverflowError) as exc:
                raise ValueError(f"Invalid generated signal for {symbol}") from exc
            if not all(math.isfinite(x) and x > 0 for x in (entry_reference, stop)):
                raise ValueError(f"Invalid entry/stop prices for {symbol}")
            if idx < 0 or idx >= len(rows_5m) - 1:
                raise ValueError(f"Signal index for {symbol} has no following candle")
            distance = entry_reference - stop if direction == "bullish" else stop - entry_reference
            if direction not in ("bullish", "bearish") or distance <= 0:
                raise ValueError(f"Invalid directional stop placement for {symbol}")

            signal["quantity"] = (initial_equity * risk_percent / 100.0) / distance
            all_signals.append(signal)

    all_signals.sort(
        key=lambda item: (
            int(candles_5m[item["symbol"]][int(item["index"]) + 1]["time"]),
            item["symbol"],
            int(item["index"]),
        )
    )

    replay = run_multi_symbol_backtest(
        candles_5m,
        all_signals,
        initial_equity=initial_equity,
        spread=spread,
        slippage=slippage,
        commission_pct=commission_pct,
        max_open_trades=max_open_trades,
        max_daily_loss_pct=max_daily_loss_pct,
        max_weekly_loss_pct=max_weekly_loss_pct,
        max_drawdown_pct=max_drawdown_pct,
    )
    return {
        **replay,
        "signal_source": "historical_smc_engine",
        "methodology_version": "historical-smc-1.0",
        "generated_signal_count": len(all_signals),
        "signal_time_start": signal_time_start,
        "signal_time_end": signal_time_end,
        "regime_filter": {
            "enabled": use_regime_filter,
            "reject_transition_regime": reject_transition_regime,
            "require_trend_alignment": require_trend_alignment,
            "reject_high_volatility": reject_high_volatility,
        },
        "generated_signals_by_symbol": {
            symbol: result["signal_count"] for symbol, result in generated.items()
        },
        "signal_generation": generated,
        "position_sizing": {
            "method": "fixed_initial_equity_risk_budget",
            "risk_percent_per_signal": risk_percent,
            "quantity_basis": "signal_entry_reference_to_stop_distance",
            "warning": (
                "Actual fill is next 5m open. Gaps and trading costs can make "
                "realized risk differ from the requested risk budget."
            ),
        },
        "execution_allowed": False,
    }
