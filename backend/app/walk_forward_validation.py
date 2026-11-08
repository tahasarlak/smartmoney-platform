"""Chronological walk-forward diagnostics for persisted paper execution outcomes.

This module evaluates already-recorded, closed paper-trade outcomes in chronological
folds. It does not retrain or optimize a signal-generation strategy. Therefore its
out-of-sample designation means later trade outcomes held out from earlier outcomes,
not a full historical market-data strategy backtest.
"""
from __future__ import annotations

import math
from datetime import datetime
from typing import Any


def _number(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _timestamp(trade: dict[str, Any]) -> float | None:
    # closed_at_ms is the preferred outcome timestamp; otherwise use ISO updated_at.
    ms = _number(trade.get("closed_at_ms"))
    if ms is not None and ms > 0:
        return ms / 1000.0
    for key in ("closed_at", "updated_at", "created_at"):
        raw = trade.get(key)
        if isinstance(raw, (int, float)) and math.isfinite(float(raw)):
            return float(raw) / (1000.0 if float(raw) > 10_000_000_000 else 1.0)
        if isinstance(raw, str):
            try:
                return datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp()
            except ValueError:
                continue
    return None


def _trade_r(trade: dict[str, Any]) -> float | None:
    if str(trade.get("status", "")).lower() != "closed":
        return None
    net = _number(trade.get("net_realized_pnl"))
    if net is None:
        pnl = _number(trade.get("realized_pnl")) or 0.0
        fees = _number(trade.get("fees_paid")) or 0.0
        net = pnl - fees
    entry = _number(trade.get("planned_entry"))
    stop = _number(trade.get("initial_stop_loss", trade.get("stop_loss")))
    qty = _number(trade.get("quantity"))
    if entry is None or stop is None or qty is None or qty <= 0:
        return None
    risk = abs(entry - stop) * qty
    if risk <= 1e-12:
        return None
    return net / risk


def _metrics(values: list[float]) -> dict[str, Any]:
    n = len(values)
    if not n:
        return {"trade_count": 0, "mean_r": None, "median_r": None,
                "win_rate_pct": None, "profit_factor_r": None, "gross_profit_r": 0.0,
                "gross_loss_r": 0.0}
    ordered = sorted(values)
    wins = [v for v in values if v > 0]
    losses = [v for v in values if v < 0]
    gp, gl = sum(wins), -sum(losses)
    mid = n // 2
    median = ordered[mid] if n % 2 else (ordered[mid - 1] + ordered[mid]) / 2
    return {
        "trade_count": n,
        "mean_r": round(sum(values) / n, 8),
        "median_r": round(median, 8),
        "win_rate_pct": round(len(wins) / n * 100.0, 4),
        "profit_factor_r": round(gp / gl, 8) if gl > 1e-12 else None,
        "gross_profit_r": round(gp, 8),
        "gross_loss_r": round(gl, 8),
    }


def build_walk_forward_validation(
    *, trades: list[dict[str, Any]], folds: int = 4, min_train_fraction: float = 0.5
) -> dict[str, Any]:
    """Create chronological expanding-history folds over closed paper trade outcomes."""
    if not isinstance(trades, list):
        raise ValueError("trades must be a list")
    if not 2 <= int(folds) <= 8:
        raise ValueError("folds must be between 2 and 8")
    if not 0.4 <= float(min_train_fraction) <= 0.8:
        raise ValueError("min_train_fraction must be between 0.4 and 0.8")

    valid = []
    skipped = 0
    for trade in trades:
        r = _trade_r(trade)
        ts = _timestamp(trade)
        if r is None or ts is None:
            skipped += 1
            continue
        valid.append({"id": str(trade.get("id", "")), "timestamp": ts, "r": r})
    valid.sort(key=lambda x: (x["timestamp"], x["id"]))
    n = len(valid)
    initial = max(2, int(math.floor(n * float(min_train_fraction))))
    remaining = n - initial
    if remaining < folds:
        actual_folds = max(0, remaining)
    else:
        actual_folds = folds
    fold_rows = []
    oos_values: list[float] = []
    cursor = initial
    for index in range(actual_folds):
        left = cursor
        # Evenly divide all remaining observations; final fold receives remainder.
        width = max(1, int(math.ceil((n - cursor) / (actual_folds - index))))
        right = min(n, left + width)
        train_values = [x["r"] for x in valid[:left]]
        test_values = [x["r"] for x in valid[left:right]]
        if not test_values:
            break
        oos_values.extend(test_values)
        fold_rows.append({
            "fold": index + 1,
            "train_start": datetime.fromtimestamp(valid[0]["timestamp"]).isoformat(),
            "train_end": datetime.fromtimestamp(valid[left - 1]["timestamp"]).isoformat(),
            "test_start": datetime.fromtimestamp(valid[left]["timestamp"]).isoformat(),
            "test_end": datetime.fromtimestamp(valid[right - 1]["timestamp"]).isoformat(),
            "train": _metrics(train_values),
            "out_of_sample": _metrics(test_values),
            "out_of_sample_positive_expectancy": sum(test_values) / len(test_values) > 0,
        })
        cursor = right

    train_values = [x["r"] for x in valid[:initial]] if n >= initial else []
    oos_mean = sum(oos_values) / len(oos_values) if oos_values else None
    positive_folds = sum(1 for row in fold_rows if row["out_of_sample_positive_expectancy"])
    if n < 30 or len(oos_values) < 10:
        status = "insufficient_sample"
        quality = "insufficient"
    elif positive_folds == len(fold_rows) and oos_mean is not None and oos_mean > 0:
        status = "oos_positive_across_folds"
        quality = "promising_not_conclusive"
    elif oos_mean is not None and oos_mean > 0:
        status = "mixed_oos"
        quality = "mixed"
    else:
        status = "oos_not_positive"
        quality = "weak"
    return {
        "status": status,
        "mode": "paper_trade_outcome_walk_forward",
        "valid_closed_trade_count": n,
        "skipped_trade_count": skipped,
        "initial_train_trade_count": len(train_values),
        "out_of_sample_trade_count": len(oos_values),
        "requested_folds": folds,
        "completed_folds": len(fold_rows),
        "sample_quality": quality,
        "in_sample": _metrics(train_values),
        "out_of_sample": _metrics(oos_values),
        "positive_oos_folds": positive_folds,
        "oos_positive_fold_pct": round(positive_folds / len(fold_rows) * 100.0, 2) if fold_rows else None,
        "folds": fold_rows,
        "methodology": {
            "ordering": "closed_at_ms_then_updated_at_then_created_at",
            "split": "chronological_expanding_training_prefix_followed_by_non_overlapping_future_test_folds",
            "unit": "net_realized_pnl_divided_by_initial_cash_risk",
            "strategy_retraining": False,
            "uses_future_market_candles": False,
        },
        "limitations": [
            "This evaluates chronological paper-trade outcomes, not a strategy re-run on historical OHLC data.",
            "No parameter fitting or strategy retraining occurs; this is not a full model walk-forward optimization.",
            "Trade outcomes may be serially dependent and may reflect prior strategy selection or execution assumptions.",
            "The sample is limited to persisted closed paper execution trades available in the selected portfolio.",
            "No profitability forecast, guarantee, or live-readiness certification is produced.",
        ],
        "execution_allowed": False,
    }
