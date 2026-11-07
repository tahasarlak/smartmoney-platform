from __future__ import annotations
from typing import Any

INTERVAL_SECONDS = {
    "1m": 60, "3m": 180, "5m": 300, "15m": 900, "30m": 1800,
    "1h": 3600, "2h": 7200, "4h": 14400, "1d": 86400,
}

def validate_candle_series(candles: list[dict[str, Any]], interval: str,
                            now_epoch: int, max_lag_bars: float = 2.5) -> dict[str, Any]:
    """Validate ordering, duplicates, OHLC consistency and last-closed-candle freshness.

    Candle `time` is assumed to be Binance kline open time in Unix seconds.
    The final array element is treated as the currently-forming candle and excluded.
    """
    if interval not in INTERVAL_SECONDS:
        return {"valid": False, "reason": f"Unsupported interval: {interval}"}
    if len(candles) < 3:
        return {"valid": False, "reason": "At least 3 candles are required"}
    times = [int(x["time"]) for x in candles]
    if times != sorted(times):
        return {"valid": False, "reason": "Candle timestamps are not ascending"}
    if len(times) != len(set(times)):
        return {"valid": False, "reason": "Duplicate candle timestamps detected"}
    for i, c in enumerate(candles):
        try:
            o, h, lo, cl = (float(c[k]) for k in ("open", "high", "low", "close"))
        except (KeyError, TypeError, ValueError):
            return {"valid": False, "reason": f"Invalid OHLC at index {i}"}
        if not (lo <= min(o, cl) <= max(o, cl) <= h):
            return {"valid": False, "reason": f"OHLC invariant violated at index {i}"}
    duration = INTERVAL_SECONDS[interval]
    last_closed_open = times[-2]
    last_closed_close = last_closed_open + duration
    age = now_epoch - last_closed_close
    if age < -duration * 0.25:
        return {"valid": False, "reason": "Last closed candle appears to be in the future",
                "last_closed_open": last_closed_open, "age_seconds": age}
    max_lag = duration * max_lag_bars
    if age > max_lag:
        return {"valid": False, "reason": "Market data is stale",
                "last_closed_open": last_closed_open, "age_seconds": age,
                "max_lag_seconds": max_lag}
    return {"valid": True, "reason": None, "last_closed_open": last_closed_open,
            "last_closed_close": last_closed_close, "age_seconds": max(0, age),
            "interval_seconds": duration}
