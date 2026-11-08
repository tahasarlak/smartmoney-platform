"""Causal train/OOS parameter search using the existing historical SMC OHLC engine.

The optimizer selects parameters on the chronological training window only, then
runs the selected parameters once on the untouched out-of-sample window.
Research only: never submits orders.
"""
from __future__ import annotations

import itertools
import math
from typing import Any, Callable


def _finite(value: Any, name: str) -> float:
    try:
        x = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{name} must be numeric") from exc
    if not math.isfinite(x):
        raise ValueError(f"{name} must be finite")
    return x


def _metrics(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "trade_count": int(result.get("trade_count", 0)),
        "net_pnl": _finite(result.get("net_pnl", 0), "net_pnl"),
        "expectancy_per_trade": result.get("expectancy_per_trade"),
        "profit_factor": result.get("profit_factor"),
        "win_rate_pct": result.get("win_rate_pct"),
        "max_drawdown_pct": _finite(result.get("max_drawdown_pct", 0), "max_drawdown_pct"),
    }


def optimize_historical_smc(
    *, candles_by_symbol_and_tf: dict[str, dict[str, list[dict[str, Any]]]],
    runner: Callable[..., dict[str, Any]], initial_equity: float = 10_000.0,
    risk_percent: float = 0.5, min_quality_scores: list[int] | None = None,
    min_rr_values: list[float] | None = None, train_fraction: float = 0.7,
    max_combinations: int = 24, min_train_trades: int = 5,
    costs: dict[str, float] | None = None,
) -> dict[str, Any]:
    if not isinstance(candles_by_symbol_and_tf, dict) or not candles_by_symbol_and_tf:
        raise ValueError("candles_by_symbol_and_tf must be a non-empty object")
    if not 0.5 <= float(train_fraction) <= 0.85:
        raise ValueError("train_fraction must be between 0.5 and 0.85")
    if not 1 <= int(max_combinations) <= 24:
        raise ValueError("max_combinations must be between 1 and 24")
    if not 1 <= int(min_train_trades) <= 100:
        raise ValueError("min_train_trades must be between 1 and 100")
    quality = min_quality_scores or [60, 65, 70]
    rr_values = min_rr_values or [1.5, 2.0, 2.5]
    if not quality or not rr_values or any(not 1 <= int(x) <= 100 for x in quality):
        raise ValueError("Invalid min_quality_scores")
    if any(not 0.5 <= _finite(x, "min_rr") <= 10 for x in rr_values):
        raise ValueError("min_rr_values must be between 0.5 and 10")
    combos = list(itertools.product(sorted(set(map(int, quality))), sorted(set(map(float, rr_values)))))
    if len(combos) > max_combinations:
        raise ValueError(f"Grid has {len(combos)} combinations; maximum is {max_combinations}")

    # Use the primary 5m timeline to establish a chronological boundary.
    all_times: list[int] = []
    for symbol, tf_data in candles_by_symbol_and_tf.items():
        if not isinstance(tf_data, dict) or not isinstance(tf_data.get("5m"), list):
            raise ValueError(f"{symbol}: missing 5m candles")
        all_times.extend(int(row["time"]) for row in tf_data["5m"])
    times = sorted(set(all_times))
    if len(times) < 100:
        raise ValueError("At least 100 distinct 5m timestamps are required")
    split_index = int(len(times) * float(train_fraction))
    split_time = times[split_index]
    if split_time <= times[0] or split_time >= times[-1]:
        raise ValueError("Invalid chronological split")

    common = dict(
        candles_by_symbol_and_tf=candles_by_symbol_and_tf,
        initial_equity=float(initial_equity), risk_percent=float(risk_percent),
        spread=float((costs or {}).get("spread", 0.0)),
        slippage=float((costs or {}).get("slippage", 0.0)),
        commission_pct=float((costs or {}).get("commission_pct", 0.0)),
        use_regime_filter=bool((costs or {}).get("use_regime_filter", False)),
    )
    candidates = []
    for q, rr in combos:
        train = runner(**common, min_quality_score=q, min_rr=rr, signal_time_end=split_time)
        m = _metrics(train)
        # Prefer positive expectancy and lower drawdown; reject tiny samples.
        expectancy = m["expectancy_per_trade"]
        exp = _finite(expectancy, "expectancy_per_trade") if expectancy is not None else -1e9
        score = (exp / (1.0 + m["max_drawdown_pct"])) if m["trade_count"] >= min_train_trades else -1e12
        candidates.append({"parameters": {"min_quality_score": q, "min_rr": rr},
                           "training": m, "selection_score": round(score, 10)})
    eligible = [c for c in candidates if c["training"]["trade_count"] >= min_train_trades]
    if not eligible:
        return {"status": "insufficient_training_sample", "candidate_count": len(candidates),
                "split_time": split_time, "candidates": candidates, "selected_parameters": None,
                "out_of_sample": None, "execution_allowed": False,
                "limitations": [f"No candidate reached {min_train_trades} training trades."]}
    best = max(eligible, key=lambda c: (c["selection_score"], c["training"]["net_pnl"]))
    p = best["parameters"]
    oos_raw = runner(**common, min_quality_score=p["min_quality_score"], min_rr=p["min_rr"],
                     signal_time_start=split_time)
    oos = _metrics(oos_raw)
    return {
        "status": "completed", "method": "chronological_train_then_single_holdout",
        "split_time": split_time, "train_fraction": float(train_fraction),
        "candidate_count": len(candidates), "selected_parameters": p,
        "selected_training": best["training"], "out_of_sample": oos,
        "candidates": candidates,
        "oos_positive_expectancy": bool(oos["expectancy_per_trade"] is not None and oos["expectancy_per_trade"] > 0),
        "execution_allowed": False,
        "limitations": [
            "Parameters are selected using training data only; OOS is evaluated once.",
            "The holdout result is not a guarantee of future profitability.",
            "The engine's OHLC intrabar and fill assumptions remain applicable.",
            "This is a bounded grid over min_quality_score and min_rr, not unrestricted parameter mining.",
        ],
    }
