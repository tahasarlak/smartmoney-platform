from __future__ import annotations

from typing import Any

from .market_regime import analyze_market_regime
from .market_regime_intelligence import analyze_market_regime_intelligence
from .scanner import TIMEFRAMES, scan_symbol
from .smc import analyze_smc
from .v8_engine import _make_plan

_INTERVAL_SECONDS = {
    "4h": 14_400,
    "1h": 3_600,
    "15m": 900,
    "5m": 300,
    "1m": 60,
}


def _validate_series(timeframe: str, rows: list[dict[str, Any]]) -> None:
    if not isinstance(rows, list):
        raise ValueError(f"{timeframe} candles must be a list")
    previous: int | None = None
    for index, row in enumerate(rows):
        try:
            timestamp = int(row["time"])
            open_, high, low, close = (
                float(row[key]) for key in ("open", "high", "low", "close")
            )
        except (KeyError, TypeError, ValueError, OverflowError) as exc:
            raise ValueError(f"Invalid {timeframe} candle at index {index}") from exc
        if timestamp < 0 or (previous is not None and timestamp <= previous):
            raise ValueError(f"{timeframe} timestamps must be strictly increasing")
        if not all(value > 0 for value in (open_, high, low, close)):
            raise ValueError(f"{timeframe} OHLC values must be positive")
        if not low <= min(open_, close) <= max(open_, close) <= high:
            raise ValueError(f"Invalid {timeframe} OHLC relationship at index {index}")
        previous = timestamp


def _closed_as_of(
    rows: list[dict[str, Any]], timeframe: str, decision_time: int
) -> list[dict[str, Any]]:
    """Return only candles whose full interval has ended by decision_time."""
    duration = _INTERVAL_SECONDS[timeframe]
    return [row for row in rows if int(row["time"]) + duration <= decision_time]


def _analysis_window(closed_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Adapt closed-only history to analyzers that reserve the last row as forming.

    Duplicating the final closed row means analyzers' `rows[:-1]` contains every
    genuinely closed candle. The duplicate is never treated as new information.
    """
    if not closed_rows:
        return []
    return [*closed_rows, closed_rows[-1]]


def generate_historical_smc_signals(
    symbol: str,
    candles_by_tf: dict[str, list[dict[str, Any]]],
    *,
    min_quality_score: int = 65,
    min_rr: float = 2.0,
    risk_percent: float = 0.5,
    allow_counter_trend: bool = False,
    max_signals: int = 500,
    history_limit: int = 500,
    use_regime_filter: bool = False,
    reject_transition_regime: bool = True,
    require_trend_alignment: bool = True,
    reject_high_volatility: bool = False,
) -> dict[str, Any]:
    """Generate causal, research-only SMC signals from multi-timeframe OHLC data.

    `time` is the candle OPEN timestamp in Unix seconds. A decision is made only
    after a 5m candle closes. Higher/lower timeframe candles are included only
    when their complete interval has closed by that decision time. The returned
    `index` points to the decision 5m candle; portfolio backtests enter at the
    following 5m candle open.

    The function deliberately does not estimate win probability or submit orders.
    """
    normalized_symbol = str(symbol).strip().upper()
    if not normalized_symbol or len(normalized_symbol) > 30:
        raise ValueError("Invalid symbol")
    if not isinstance(candles_by_tf, dict):
        raise ValueError("candles_by_tf must be a dictionary")
    missing = [tf for tf in TIMEFRAMES if tf not in candles_by_tf]
    if missing:
        raise ValueError(f"Missing timeframes: {', '.join(missing)}")
    if not isinstance(min_quality_score, int) or not 0 <= min_quality_score <= 100:
        raise ValueError("min_quality_score must be between 0 and 100")
    if not 0.5 <= float(min_rr) <= 10:
        raise ValueError("min_rr must be between 0.5 and 10")
    if not 0 < float(risk_percent) <= 2:
        raise ValueError("risk_percent must be greater than 0 and at most 2")
    if not isinstance(max_signals, int) or not 1 <= max_signals <= 10_000:
        raise ValueError("max_signals must be between 1 and 10000")
    if not isinstance(history_limit, int) or not 50 <= history_limit <= 5_000:
        raise ValueError("history_limit must be between 50 and 5000")

    rows_by_tf = {tf: candles_by_tf[tf] for tf in TIMEFRAMES}
    for tf, rows in rows_by_tf.items():
        _validate_series(tf, rows)
    if len(rows_by_tf["5m"]) < 2:
        raise ValueError("At least two 5m candles are required")

    five_minute_rows = rows_by_tf["5m"]
    signals: list[dict[str, Any]] = []
    rejected: dict[str, int] = {
        "insufficient_history": 0,
        "no_confirmed_setup": 0,
        "invalid_plan": 0,
        "duplicate_zone": 0,
        "regime_filter": 0,
    }
    regime_observations: dict[str, int] = {}
    seen_zones: set[tuple[str, str, str]] = set()

    # The final 5m row has no following candle, so it cannot be replayed by
    # the backtester at the next candle open.
    for decision_index in range(len(five_minute_rows) - 1):
        decision_candle = five_minute_rows[decision_index]
        decision_time = int(decision_candle["time"]) + _INTERVAL_SECONDS["5m"]

        closed_by_tf = {
            tf: _closed_as_of(rows_by_tf[tf], tf, decision_time)
            for tf in TIMEFRAMES
        }
        if any(len(closed_by_tf[tf]) < 50 for tf in TIMEFRAMES):
            rejected["insufficient_history"] += 1
            continue

        # A bounded rolling window keeps historical generation tractable while
        # preserving enough context for the current SMC and regime calculations.
        bounded = {tf: closed_by_tf[tf][-history_limit:] for tf in TIMEFRAMES}
        windows = {tf: _analysis_window(bounded[tf]) for tf in TIMEFRAMES}
        analyses = {
            tf: analyze_smc(normalized_symbol, windows[tf], swing_length=3)
            for tf in TIMEFRAMES
        }
        regimes = {
            tf: analyze_market_regime(windows[tf], tf)
            for tf in TIMEFRAMES
        }
        aggregate_regime = analyze_market_regime_intelligence(
            {tf: windows[tf] for tf in ("4h", "1h", "15m", "5m")}
        )
        regime_name = str(aggregate_regime["aggregate_regime"])
        regime_observations[regime_name] = regime_observations.get(regime_name, 0) + 1
        scan = scan_symbol(
            normalized_symbol,
            windows,
            analyses,
            settings={
                "min_quality_score": min_quality_score,
                "min_rr": float(min_rr),
                "allow_counter_trend": allow_counter_trend,
            },
            regimes=regimes,
        )

        candidates = [
            scenario for scenario in scan.get("scenarios", [])
            if scenario.get("confirmation") == "confirmed_trigger"
            and int(scenario.get("quality_score", 0)) >= min_quality_score
            and isinstance(scenario.get("zone"), dict)
        ]
        if not candidates:
            rejected["no_confirmed_setup"] += 1
            continue

        for scenario in candidates:
            direction = str(scenario.get("direction", ""))
            if use_regime_filter:
                policy_reject = (
                    (reject_transition_regime and regime_name in {"transition", "mixed_trend"})
                    or (
                        require_trend_alignment
                        and regime_name == "trending"
                        and aggregate_regime["dominant_direction"] not in {"neutral", direction}
                    )
                    or (
                        reject_high_volatility
                        and aggregate_regime["volatility_state"] == "high_volatility"
                    )
                )
                if policy_reject:
                    rejected["regime_filter"] += 1
                    continue
            zone = scenario["zone"]
            zone_key = (
                direction,
                str(zone.get("formed_at")),
                str(zone.get("type")),
            )
            if zone_key in seen_zones:
                rejected["duplicate_zone"] += 1
                continue

            plan = _make_plan(
                normalized_symbol,
                scenario,
                windows,
                float(min_rr),
                float(risk_percent),
            )
            if not plan or not plan.get("rr_filter_passed"):
                rejected["invalid_plan"] += 1
                continue

            targets = plan.get("take_profits") or []
            if len(targets) < 2:
                rejected["invalid_plan"] += 1
                continue
            take_profit = float(targets[1]["price"])
            stop_loss = float(plan["stop_loss"])
            entry_reference = float(plan["entry"])
            if direction not in ("bullish", "bearish"):
                rejected["invalid_plan"] += 1
                continue

            # Preserve all plan targets for the partial-exit simulator.
            # Fractions are deterministic defaults, not optimized parameters.
            target_prices = [float(item["price"]) for item in targets[:3]]
            if len(target_prices) >= 3:
                target_fractions = [0.50, 0.30, 0.20]
            elif len(target_prices) == 2:
                target_fractions = [0.50, 0.50]
            else:
                target_prices = [take_profit]
                target_fractions = [1.0]
            take_profit_levels = [
                {"price": price, "fraction": fraction}
                for price, fraction in zip(target_prices, target_fractions)
            ]

            signals.append({
                "symbol": normalized_symbol,
                "index": decision_index,
                "direction": direction,
                "stop_loss": stop_loss,
                "take_profit": take_profit,
                "take_profits": take_profit_levels,
                "break_even_after_tp1": True,
                "entry_reference": entry_reference,
                "quality_score": int(scenario["quality_score"]),
                "minimum_rr": float(min_rr),
                "risk_percent_setting": float(risk_percent),
                "signal_time": decision_time,
                "market_regime": {
                    "aggregate_regime": regime_name,
                    "dominant_direction": aggregate_regime["dominant_direction"],
                    "volatility_state": aggregate_regime["volatility_state"],
                    "trend_alignment_count": aggregate_regime["trend_alignment_count"],
                },
                "zone": {
                    "type": zone.get("type"),
                    "low": float(zone["low"]),
                    "high": float(zone["high"]),
                    "formed_at": zone.get("formed_at"),
                },
                "methodology_version": "historical-smc-1.0",
                "execution_allowed": False,
            })
            seen_zones.add(zone_key)
            if len(signals) >= max_signals:
                break
        if len(signals) >= max_signals:
            break

    signals.sort(key=lambda item: (item["signal_time"], item["symbol"], item["direction"]))
    return {
        "status": "completed",
        "symbol": normalized_symbol,
        "methodology_version": "historical-smc-1.0",
        "decision_timeframe": "5m",
        "entry_timing": "next_5m_candle_open",
        "signal_count": len(signals),
        "signals": signals,
        "rejected_counts": rejected,
        "market_regime_summary": regime_observations,
        "regime_filter": {
            "enabled": use_regime_filter,
            "reject_transition_regime": reject_transition_regime,
            "require_trend_alignment": require_trend_alignment,
            "reject_high_volatility": reject_high_volatility,
        },
        "estimated_win_probability": None,
        "probability_status": "not_estimated_requires_out_of_sample_calibration",
        "lookahead_policy": {
            "candle_time_semantics": "unix_seconds_candle_open",
            "only_fully_closed_timeframe_candles": True,
            "higher_timeframe_close_boundary_enforced": True,
            "entry_occurs_after_signal_candle": True,
            "future_bars_used_for_signal_generation": False,
        },
        "limitations": [
            "Rule-based SMC approximation; not a claim of predictive edge.",
            "The backtester must model fees, spread, slippage and same-bar stop/target ambiguity.",
            "Signals use one 5m decision timeline and require sufficient history on every timeframe.",
        ],
    }
