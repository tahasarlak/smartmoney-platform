from __future__ import annotations

import math
from statistics import median
from typing import Any


def analyze_market_regime(
    candles: list[dict[str, Any]],
    timeframe: str,
    *,
    trend_threshold: float = 0.35,
    range_threshold: float = 0.20,
) -> dict[str, Any]:
    """Describe trend, volatility and participation using CLOSED candles only.

    This is contextual market classification, not a predictive model and not
    a win-probability estimate. The final input candle is treated as forming.
    """
    if not 0.0 <= range_threshold < trend_threshold <= 1.0:
        raise ValueError("Invalid regime thresholds")
    if len(candles) < 32:
        raise ValueError("At least 32 candles are required for regime analysis")

    closed = sorted(candles[:-1], key=lambda row: int(row["time"]))
    normalized: list[dict[str, float]] = []
    for index, row in enumerate(closed):
        try:
            values = {key: float(row[key]) for key in ("open", "high", "low", "close")}
            volume = float(row.get("volume", 0.0))
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"Invalid candle at closed index {index}") from exc
        if not all(math.isfinite(value) for value in values.values()):
            raise ValueError(f"Non-finite OHLC value at closed index {index}")
        if not math.isfinite(volume) or volume < 0:
            raise ValueError(f"Invalid volume at closed index {index}")
        if values["low"] <= 0 or not (
            values["low"] <= min(values["open"], values["close"])
            <= max(values["open"], values["close"]) <= values["high"]
        ):
            raise ValueError(f"Invalid OHLC relationship at closed index {index}")
        normalized.append({**values, "volume": volume})

    closes = [row["close"] for row in normalized]
    true_ranges: list[float] = []
    for index in range(1, len(normalized)):
        row, previous_close = normalized[index], closes[index - 1]
        true_ranges.append(max(
            row["high"] - row["low"],
            abs(row["high"] - previous_close),
            abs(row["low"] - previous_close),
        ))

    atr_values = [
        sum(true_ranges[index - 14:index]) / 14
        for index in range(14, len(true_ranges) + 1)
    ]
    atr = atr_values[-1] if atr_values else 0.0
    baseline = median(atr_values[-50:]) if atr_values else 0.0
    volatility_ratio = atr / baseline if baseline > 0 else 1.0
    atr_pct = atr / closes[-1] * 100 if closes[-1] > 0 else 0.0

    lookback = min(20, len(closes) - 1)
    net_move = abs(closes[-1] - closes[-1 - lookback])
    path_move = sum(abs(closes[i] - closes[i - 1])
                    for i in range(len(closes) - lookback, len(closes)))
    efficiency = net_move / path_move if path_move > 0 else 0.0
    delta = closes[-1] - closes[-1 - lookback]
    direction = "bullish" if delta > 0 else "bearish" if delta < 0 else "neutral"

    if efficiency >= trend_threshold:
        regime = "trending"
    elif efficiency <= range_threshold:
        regime = "ranging"
    else:
        regime = "transition"

    if volatility_ratio >= 1.5:
        volatility = "expanded"
    elif volatility_ratio <= 0.75:
        volatility = "compressed"
    else:
        volatility = "normal"

    volumes = [row["volume"] for row in normalized]
    recent_volume = volumes[-1]
    volume_baseline = median(volumes[-21:-1]) if len(volumes) > 1 else 0.0
    volume_ratio = recent_volume / volume_baseline if volume_baseline > 0 else None
    if volume_ratio is None:
        participation = "unavailable"
    elif volume_ratio >= 1.5:
        participation = "high"
    elif volume_ratio <= 0.6:
        participation = "low"
    else:
        participation = "normal"

    return {
        "timeframe": timeframe,
        "regime": regime,
        "trend_direction": direction if regime == "trending" else "neutral",
        "trend_efficiency": round(efficiency, 4),
        "volatility_regime": volatility,
        "atr": round(atr, 10),
        "atr_percent": round(atr_pct, 6),
        "volatility_ratio_to_baseline": round(volatility_ratio, 4),
        "volume_participation": participation,
        "volume_ratio_to_baseline": round(volume_ratio, 4) if volume_ratio is not None else None,
        "closed_candles": len(closed),
        "closed_candle_only": True,
        "estimated_win_probability": None,
    }
