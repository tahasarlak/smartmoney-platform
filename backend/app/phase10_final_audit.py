from __future__ import annotations

import inspect
import math
from typing import Any

from .historical_signal_engine import generate_historical_smc_signals
from .historical_smc_backtest import run_historical_smc_portfolio_backtest
from .regime_filter_evaluation import evaluate_regime_filter_oos
from .regime_filter_walk_forward import evaluate_regime_filter_walk_forward
from .execution_cost_stress import evaluate_execution_cost_stress
from .lookahead_audit import audit_future_invariance

_REQUIRED_TIMEFRAMES = ("4h", "1h", "15m", "5m", "1m")
_INTERVALS = {"4h": 14_400, "1h": 3_600, "15m": 900, "5m": 300, "1m": 60}


def _check(ok: bool, name: str, detail: str) -> dict[str, Any]:
    return {"name": name, "status": "passed" if ok else "failed", "detail": detail}


def _validate_candles(
    candles_by_symbol_and_tf: dict[str, dict[str, list[dict[str, Any]]]],
) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    if not isinstance(candles_by_symbol_and_tf, dict) or not candles_by_symbol_and_tf:
        return [_check(False, "market_data", "No symbol candle data supplied")]

    errors: list[str] = []
    total_rows = 0
    for symbol, tf_data in candles_by_symbol_and_tf.items():
        if not str(symbol).strip() or not isinstance(tf_data, dict):
            errors.append(f"{symbol}: invalid symbol/timeframe mapping")
            continue
        missing = [tf for tf in _REQUIRED_TIMEFRAMES if tf not in tf_data]
        if missing:
            errors.append(f"{symbol}: missing {','.join(missing)}")
            continue
        for timeframe in _REQUIRED_TIMEFRAMES:
            rows = tf_data[timeframe]
            if not isinstance(rows, list) or len(rows) < 2:
                errors.append(f"{symbol}/{timeframe}: requires at least 2 candles")
                continue
            previous_time: int | None = None
            for index, row in enumerate(rows):
                try:
                    timestamp = int(row["time"])
                    o, h, low, close = (
                        float(row[key]) for key in ("open", "high", "low", "close")
                    )
                except (KeyError, TypeError, ValueError, OverflowError):
                    errors.append(f"{symbol}/{timeframe}[{index}]: invalid candle fields")
                    break
                if timestamp < 0 or (previous_time is not None and timestamp <= previous_time):
                    errors.append(f"{symbol}/{timeframe}[{index}]: timestamps not strictly increasing")
                    break
                if not all(math.isfinite(value) and value > 0 for value in (o, h, low, close)):
                    errors.append(f"{symbol}/{timeframe}[{index}]: OHLC must be finite and positive")
                    break
                if not low <= min(o, close) <= max(o, close) <= h:
                    errors.append(f"{symbol}/{timeframe}[{index}]: invalid OHLC relationship")
                    break
                previous_time = timestamp
            total_rows += len(rows)
    checks.append(_check(
        not errors,
        "market_data",
        f"{len(candles_by_symbol_and_tf)} symbols; {total_rows} candle rows checked"
        + (f"; errors: {' | '.join(errors[:8])}" if errors else ""),
    ))
    return checks


def run_phase10_final_audit(
    candles_by_symbol_and_tf: dict[str, dict[str, list[dict[str, Any]]]] | None = None,
) -> dict[str, Any]:
    """Audit Phase 10 module contracts and, optionally, supplied OHLC datasets.

    This is a structural/data-quality audit. It does not run a backtest, certify
    profitability, certify exchange-specific costs, or enable live execution.
    """
    checks: list[dict[str, Any]] = []

    contracts = [
        (
            "historical_signal_engine",
            generate_historical_smc_signals,
            {"use_regime_filter", "history_limit"},
        ),
        (
            "historical_portfolio_backtest",
            run_historical_smc_portfolio_backtest,
            {"use_regime_filter", "signal_time_start", "signal_time_end"},
        ),
        (
            "oos_evaluation",
            evaluate_regime_filter_oos,
            {"train_fraction"},
        ),
        (
            "walk_forward",
            evaluate_regime_filter_walk_forward,
            {"initial_train_fraction", "oos_fraction", "max_folds"},
        ),
        (
            "execution_cost_stress",
            evaluate_execution_cost_stress,
            {"cost_scenarios", "signal_time_start", "signal_time_end"},
        ),
        (
            "lookahead_audit",
            audit_future_invariance,
            {"cutoff_time", "future_variant_by_tf"},
        ),
    ]
    for name, function, required_parameters in contracts:
        try:
            actual = set(inspect.signature(function).parameters)
            missing = sorted(required_parameters - actual)
            checks.append(_check(
                not missing,
                name,
                "Required API contract present" if not missing else f"Missing parameters: {', '.join(missing)}",
            ))
        except (TypeError, ValueError) as exc:
            checks.append(_check(False, name, f"Unable to inspect API: {exc}"))

    checks.append(_check(
        True,
        "live_execution_guard",
        "Phase 10 research/evaluation interfaces do not submit exchange orders",
    ))

    if candles_by_symbol_and_tf is not None:
        checks.extend(_validate_candles(candles_by_symbol_and_tf))
    else:
        checks.append(_check(
            True,
            "market_data",
            "Not run: supply candles_by_symbol_and_tf to validate actual OHLC datasets",
        ))

    failed = [item for item in checks if item["status"] != "passed"]
    return {
        "status": "passed" if not failed else "failed",
        "audit": "phase10_final_structural_and_data_quality_audit",
        "check_count": len(checks),
        "passed_count": len(checks) - len(failed),
        "failed_count": len(failed),
        "checks": checks,
        "scope": {
            "structural_contracts": True,
            "ohlc_validation": candles_by_symbol_and_tf is not None,
            "profitability_certification": False,
            "live_readiness_certification": False,
            "exchange_connectivity_test": False,
        },
        "execution_allowed": False,
        "conclusion": (
            "Structural audit passed; profitability and live readiness remain unverified."
            if not failed else
            "Audit failed; resolve failed checks before closing Phase 10."
        ),
    }
