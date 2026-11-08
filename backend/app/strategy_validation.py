"""Statistical validation for persisted paper execution outcomes.

Bootstrap summaries are descriptive uncertainty diagnostics, not a guarantee,
forecast, or proof that a strategy will remain profitable.
"""
from __future__ import annotations

import math
import random
from typing import Any


def _finite(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * p
    low = int(math.floor(position))
    high = int(math.ceil(position))
    if low == high:
        return ordered[low]
    weight = position - low
    return ordered[low] * (1.0 - weight) + ordered[high] * weight


def _wilson_interval(wins: int, n: int, z: float = 1.959963984540054) -> tuple[float, float] | tuple[None, None]:
    if n <= 0:
        return None, None
    phat = wins / n
    denom = 1.0 + z * z / n
    center = (phat + z * z / (2.0 * n)) / denom
    margin = z * math.sqrt((phat * (1.0 - phat) / n) + z * z / (4.0 * n * n)) / denom
    return max(0.0, center - margin) * 100.0, min(1.0, center + margin) * 100.0


def build_strategy_validation(*, trades: list[dict[str, Any]], bootstrap_iterations: int = 2000) -> dict[str, Any]:
    """Validate a closed paper-trade sample using R-multiples and bootstrap CIs."""
    if not isinstance(trades, list):
        raise ValueError("trades must be a list")
    if not 500 <= int(bootstrap_iterations) <= 10000:
        raise ValueError("bootstrap_iterations must be between 500 and 10000")

    sample: list[dict[str, Any]] = []
    for trade in trades:
        if str(trade.get("status", "")).lower() != "closed":
            continue
        net = _finite(trade.get("net_realized_pnl"))
        if net is None:
            realized = _finite(trade.get("realized_pnl")) or 0.0
            fees = _finite(trade.get("fees_paid")) or 0.0
            net = realized - fees
        entry = _finite(trade.get("planned_entry"))
        stop = _finite(trade.get("initial_stop_loss", trade.get("stop_loss")))
        quantity = _finite(trade.get("quantity"))
        if entry is None or stop is None or quantity is None or quantity <= 0:
            continue
        initial_risk = abs(entry - stop) * quantity
        if initial_risk <= 1e-12:
            continue
        sample.append({
            "id": str(trade.get("id", "")),
            "symbol": str(trade.get("symbol", "UNKNOWN")).upper(),
            "side": str(trade.get("side", "unknown")).lower(),
            "net_pnl": net,
            "r": net / initial_risk,
        })

    rs = [item["r"] for item in sample]
    pnls = [item["net_pnl"] for item in sample]
    n = len(rs)
    wins = sum(1 for value in rs if value > 0)
    win_low, win_high = _wilson_interval(wins, n)
    mean_r = sum(rs) / n if n else None
    median_r = _percentile(rs, 0.5)
    expectancy_low = expectancy_high = positive_bootstrap_share = None

    if n >= 2:
        # Deterministic resampling makes the report reproducible for the same sample.
        seed_material = "|".join(sorted(item["id"] for item in sample)) or str(n)
        seed = sum((i + 1) * ord(ch) for i, ch in enumerate(seed_material))
        rng = random.Random(seed)
        means: list[float] = []
        positive_count = 0
        for _ in range(bootstrap_iterations):
            draw_mean = sum(rs[rng.randrange(n)] for _ in range(n)) / n
            means.append(draw_mean)
            if draw_mean > 0:
                positive_count += 1
        expectancy_low = _percentile(means, 0.025)
        expectancy_high = _percentile(means, 0.975)
        positive_bootstrap_share = positive_count / bootstrap_iterations

    longest_losing_streak = current_losing_streak = 0
    for value in rs:
        if value < 0:
            current_losing_streak += 1
            longest_losing_streak = max(longest_losing_streak, current_losing_streak)
        else:
            current_losing_streak = 0

    gross_profit = sum(x for x in pnls if x > 0)
    gross_loss = -sum(x for x in pnls if x < 0)
    profit_factor = gross_profit / gross_loss if gross_loss > 1e-12 else None
    if n < 30:
        sample_quality = "insufficient"
        status = "insufficient_sample"
    elif n < 100:
        sample_quality = "preliminary"
        status = "preliminary"
    else:
        sample_quality = "larger_sample"
        status = "reviewable"

    ci_excludes_zero = bool(n >= 30 and expectancy_low is not None and expectancy_low > 0)
    warnings = []
    if n < 30:
        warnings.append("Fewer than 30 valid closed trades: statistical evidence is insufficient.")
    elif n < 100:
        warnings.append("Sample is preliminary; avoid treating the estimates as conclusive.")
    if ci_excludes_zero:
        warnings.append("The bootstrap 95% interval is above zero in this sample; this is not proof of future profitability.")
    else:
        warnings.append("The bootstrap 95% interval does not establish positive expectancy with this sample.")
    warnings.append("Results are conditional on recorded trades and do not account for selection bias or unobserved market regimes.")

    return {
        "status": status,
        "mode": "paper",
        "closed_trade_count": n,
        "valid_r_observations": n,
        "sample_quality": sample_quality,
        "mean_r": round(mean_r, 8) if mean_r is not None else None,
        "median_r": round(median_r, 8) if median_r is not None else None,
        "win_rate_pct": round(wins / n * 100.0, 6) if n else None,
        "win_rate_ci95_pct": [round(win_low, 6), round(win_high, 6)] if win_low is not None else None,
        "expectancy_r_ci95": [round(expectancy_low, 8), round(expectancy_high, 8)] if expectancy_low is not None else None,
        "bootstrap_positive_expectancy_share": round(positive_bootstrap_share, 6) if positive_bootstrap_share is not None else None,
        "bootstrap_iterations": bootstrap_iterations if n >= 2 else 0,
        "bootstrap_ci_excludes_zero": ci_excludes_zero,
        "profit_factor": round(profit_factor, 8) if profit_factor is not None else None,
        "longest_losing_streak": longest_losing_streak,
        "best_trade_r": round(max(rs), 8) if rs else None,
        "worst_trade_r": round(min(rs), 8) if rs else None,
        "p05_trade_r": round(_percentile(rs, 0.05), 8) if rs else None,
        "p95_trade_r": round(_percentile(rs, 0.95), 8) if rs else None,
        "warnings": warnings,
        "methodology": {
            "sample": "persisted_closed_paper_execution_trades_only",
            "unit": "net_realized_pnl_divided_by_initial_cash_risk",
            "expectancy_interval": "nonparametric_percentile_bootstrap_95_percent",
            "win_rate_interval": "wilson_score_95_percent",
            "bootstrap_is_forecast": False,
            "strategy_identity": "not_available; all valid closed execution trades in portfolio are pooled",
        },
        "limitations": [
            "This is a portfolio-level trade sample, not a verified strategy-specific backtest.",
            "Bootstrap intervals assume the observed trades are representative; serial dependence and regime changes can invalidate that assumption.",
            "No out-of-sample split, walk-forward retraining, or multiple-testing correction is performed by this endpoint.",
            "The bootstrap positive-expectancy share is a resampling frequency, not a posterior probability of future profit.",
            "No forecast, profitability guarantee, or live-readiness certification is produced.",
        ],
        "execution_allowed": False,
    }
