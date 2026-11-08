from __future__ import annotations

from copy import deepcopy
from typing import Any

from .historical_signal_engine import generate_historical_smc_signals


def audit_future_invariance(
    symbol: str,
    original_candles_by_tf: dict[str, list[dict[str, Any]]],
    future_variant_by_tf: dict[str, list[dict[str, Any]]],
    *,
    cutoff_time: int,
    generator_kwargs: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Compare historical signals through cutoff after changing only future bars.

    `cutoff_time` is a Unix timestamp. The caller must ensure the two datasets
    are identical for every candle whose interval closes on/before the cutoff.
    This function verifies that pre-cutoff candle equality before running both
    generations. It then compares canonical pre-cutoff signals.
    """
    if not isinstance(cutoff_time, int) or cutoff_time < 0:
        raise ValueError("cutoff_time must be a non-negative integer")
    if set(original_candles_by_tf) != set(future_variant_by_tf):
        raise ValueError("Both datasets must contain the same timeframe keys")

    durations = {"4h": 14_400, "1h": 3_600, "15m": 900, "5m": 300, "1m": 60}
    for timeframe in original_candles_by_tf:
        if timeframe not in durations:
            raise ValueError(f"Unsupported timeframe: {timeframe}")
        original = original_candles_by_tf[timeframe]
        variant = future_variant_by_tf[timeframe]
        original_prefix = [
            row for row in original if int(row["time"]) + durations[timeframe] <= cutoff_time
        ]
        variant_prefix = [
            row for row in variant if int(row["time"]) + durations[timeframe] <= cutoff_time
        ]
        if original_prefix != variant_prefix:
            raise ValueError(
                f"Datasets differ in information available by cutoff for {timeframe}"
            )

    kwargs = dict(generator_kwargs or {})
    original_result = generate_historical_smc_signals(
        symbol, deepcopy(original_candles_by_tf), **kwargs
    )
    variant_result = generate_historical_smc_signals(
        symbol, deepcopy(future_variant_by_tf), **kwargs
    )

    def canonical(result: dict[str, Any]) -> list[dict[str, Any]]:
        selected = [
            signal for signal in result.get("signals", [])
            if int(signal.get("signal_time", -1)) <= cutoff_time
        ]
        return sorted(selected, key=lambda signal: (
            int(signal["signal_time"]),
            str(signal.get("symbol", "")),
            str(signal.get("direction", "")),
        ))

    left, right = canonical(original_result), canonical(variant_result)
    return {
        "status": "passed" if left == right else "failed",
        "cutoff_time": cutoff_time,
        "original_pre_cutoff_signal_count": len(left),
        "variant_pre_cutoff_signal_count": len(right),
        "signals_identical": left == right,
        "execution_allowed": False,
        "methodology": "future_data_perturbation_invariance",
    }
