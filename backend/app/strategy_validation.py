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


def _wf_normalize_candles(candles_by_symbol):
    if not isinstance(candles_by_symbol, dict) or not candles_by_symbol:
        raise ValueError("At least one symbol is required")
    normalized, times = {}, {}
    if len(candles_by_symbol) > 30:
        raise ValueError("Maximum 30 symbols are supported")
    for raw_symbol, rows in candles_by_symbol.items():
        symbol = str(raw_symbol).strip().upper()
        if not symbol or symbol in normalized:
            raise ValueError(f"Invalid or duplicate symbol: {raw_symbol}")
        if not isinstance(rows, list) or len(rows) < 3:
            raise ValueError(f"At least 3 candles are required for {symbol}")
        clean, stamps = [], []
        for i, row in enumerate(rows):
            try:
                ts = int(row["time"])
                o, h, lo, cl = (float(row[k]) for k in ("open", "high", "low", "close"))
            except (KeyError, TypeError, ValueError, OverflowError) as exc:
                raise ValueError(f"Invalid candle for {symbol} at index {i}") from exc
            if not all(math.isfinite(x) and x > 0 for x in (o, h, lo, cl)):
                raise ValueError(f"Invalid OHLC values for {symbol} at index {i}")
            if not lo <= min(o, cl) <= max(o, cl) <= h:
                raise ValueError(f"OHLC invariant violated for {symbol} at index {i}")
            item = dict(row)
            item.update(time=ts, open=o, high=h, low=lo, close=cl)
            clean.append(item)
            stamps.append(ts)
        if stamps != sorted(stamps) or len(stamps) != len(set(stamps)):
            raise ValueError(f"Candles for {symbol} must be strictly chronological without duplicates")
        normalized[symbol], times[symbol] = clean, stamps
    return normalized, times


def _wf_fold_input(normalized, times, signals, start, end):
    fold_candles, index_maps = {}, {}
    for symbol, rows in normalized.items():
        indexes = [i for i, ts in enumerate(times[symbol]) if start <= ts <= end]
        if len(indexes) < 3:
            continue
        first, last = indexes[0], indexes[-1]
        fold_candles[symbol] = rows[first:last + 1]
        index_maps[symbol] = {old: old - first for old in range(first, last + 1)}

    fold_signals = []
    for raw in signals:
        if not isinstance(raw, dict):
            raise ValueError("Each signal must be an object")
        try:
            symbol = str(raw["symbol"]).strip().upper()
            idx = int(raw["index"])
        except (KeyError, TypeError, ValueError, OverflowError) as exc:
            raise ValueError("Invalid signal symbol or index") from exc
        if symbol not in normalized:
            raise ValueError(f"Signal references unknown symbol: {symbol}")
        if idx < 0 or idx >= len(normalized[symbol]) - 1:
            raise ValueError(f"Signal index for {symbol} must have a following candle")
        if not start <= times[symbol][idx] <= end:
            continue
        mapping = index_maps.get(symbol, {})
        if idx not in mapping or idx + 1 not in mapping:
            continue
        item = dict(raw)
        item["symbol"], item["index"] = symbol, mapping[idx]
        fold_signals.append(item)
    return fold_candles, fold_signals


def _wf_mc(pnls, simulations, seed, initial_equity):
    if len(pnls) < 5:
        return {
            "status": "insufficient_data", "trade_count": len(pnls),
            "simulations": 0,
            "reason": "At least 5 out-of-sample trades are required.",
            "execution_allowed": False,
        }
    rng = random.Random(seed)
    endings, drawdowns = [], []
    for _ in range(simulations):
        equity = peak = float(initial_equity)
        max_dd = 0.0
        for _ in pnls:
            equity += pnls[rng.randrange(len(pnls))]
            peak = max(peak, equity)
            if peak > 0:
                max_dd = max(max_dd, (peak - equity) / peak * 100)
        endings.append(equity - initial_equity)
        drawdowns.append(max_dd)
    return {
        "status": "completed", "trade_count": len(pnls),
        "simulations": simulations,
        "ending_net_pnl_p05": round(_percentile(endings, .05), 8),
        "ending_net_pnl_median": round(_percentile(endings, .5), 8),
        "ending_net_pnl_p95": round(_percentile(endings, .95), 8),
        "max_drawdown_pct_p50": round(_percentile(drawdowns, .5), 8),
        "max_drawdown_pct_p95": round(_percentile(drawdowns, .95), 8),
        "method": "bootstrap_resampling_of_observed_oos_trade_pnls",
        "is_forecast": False, "execution_allowed": False,
    }


def validate_strategy_walk_forward(
    candles_by_symbol, signals, *, initial_equity=10000.0,
    spread=0.0, slippage=0.0, commission_pct=0.0,
    max_open_trades=3, max_daily_loss_pct=3.0,
    max_weekly_loss_pct=6.0, max_drawdown_pct=15.0,
    folds=4, monte_carlo_simulations=1000, random_seed=42,
    stress_cost_multiplier=2.0,
):
    """Chronological independent-fold OOS replay; research only, never execution."""
    from .multi_backtesting import run_multi_symbol_backtest

    normalized, times = _wf_normalize_candles(candles_by_symbol)
    if not isinstance(signals, list):
        raise ValueError("signals must be a list")
    if not isinstance(folds, int) or not 2 <= folds <= 10:
        raise ValueError("folds must be between 2 and 10")
    if not isinstance(monte_carlo_simulations, int) or not 100 <= monte_carlo_simulations <= 10000:
        raise ValueError("monte_carlo_simulations must be between 100 and 10000")
    if not isinstance(random_seed, int) or not 0 <= random_seed <= 2**32 - 1:
        raise ValueError("random_seed must be an unsigned 32-bit integer")

    try:
        initial_equity, spread, slippage, commission_pct = map(
            float, (initial_equity, spread, slippage, commission_pct)
        )
        stress_cost_multiplier = float(stress_cost_multiplier)
        max_daily_loss_pct, max_weekly_loss_pct, max_drawdown_pct = map(
            float, (max_daily_loss_pct, max_weekly_loss_pct, max_drawdown_pct)
        )
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("Backtest configuration values must be numeric") from exc
    if not math.isfinite(initial_equity) or initial_equity <= 0:
        raise ValueError("initial_equity must be finite and positive")
    for name, value in (("spread", spread), ("slippage", slippage), ("commission_pct", commission_pct)):
        if not math.isfinite(value) or value < 0:
            raise ValueError(f"{name} must be finite and nonnegative")
    if commission_pct > 5:
        raise ValueError("commission_pct cannot exceed 5")
    for name, value in (("max_daily_loss_pct", max_daily_loss_pct),
                        ("max_weekly_loss_pct", max_weekly_loss_pct),
                        ("max_drawdown_pct", max_drawdown_pct)):
        if not math.isfinite(value) or not 0 <= value <= 100:
            raise ValueError(f"{name} must be between 0 and 100")
    if not math.isfinite(stress_cost_multiplier) or not 1 <= stress_cost_multiplier <= 10:
        raise ValueError("stress_cost_multiplier must be between 1 and 10")
    if not isinstance(max_open_trades, int) or not 1 <= max_open_trades <= 100:
        raise ValueError("max_open_trades must be between 1 and 100")

    timeline = sorted({ts for values in times.values() for ts in values})
    if len(timeline) < folds * 3:
        raise ValueError("Not enough chronological market bars for requested folds")
    ranges = []
    for i in range(folds):
        left, right = (i * len(timeline)) // folds, ((i + 1) * len(timeline)) // folds
        if right > left:
            ranges.append((timeline[left], timeline[right - 1]))

    def replay(candles, fold_signals, multiplier=1.0):
        return run_multi_symbol_backtest(
            candles, fold_signals, initial_equity=initial_equity,
            spread=spread * multiplier, slippage=slippage * multiplier,
            commission_pct=commission_pct * multiplier,
            max_open_trades=max_open_trades,
            max_daily_loss_pct=max_daily_loss_pct,
            max_weekly_loss_pct=max_weekly_loss_pct,
            max_drawdown_pct=max_drawdown_pct,
        )

    fold_reports, stress_reports, trades, stress_trades = [], [], [], []
    for number, (start, end) in enumerate(ranges, 1):
        fc, fs = _wf_fold_input(normalized, times, signals, start, end)
        if not fc:
            fold_reports.append({
                "fold": number, "status": "insufficient_market_window",
                "start_time": start, "end_time": end, "trade_count": 0,
                "net_pnl": 0.0, "max_drawdown_pct": None, "rejected_signals": [],
            })
            continue
        result = replay(fc, fs)
        fold_trades = result["trades"]
        trades.extend([{**t, "oos_fold": number} for t in fold_trades])
        fold_reports.append({
            "fold": number, "status": "completed", "start_time": start,
            "end_time": end, "symbols": list(fc), "signal_count": len(fs),
            "trade_count": result["trade_count"], "wins": result["wins"],
            "losses": result["losses"], "win_rate_pct": result["win_rate_pct"],
            "net_pnl": result["net_pnl"], "profit_factor": result["profit_factor"],
            "max_drawdown_pct": result["max_drawdown_pct"],
            "expectancy_per_trade": result["expectancy_per_trade"],
            "trades": fold_trades, "rejected_signals": result["rejected_signals"],
            "assumptions": result["assumptions"], "execution_allowed": False,
        })
        stressed = replay(fc, fs, stress_cost_multiplier)
        stress_trades.extend(stressed["trades"])
        stress_reports.append({
            "fold": number, "status": "completed",
            "trade_count": stressed["trade_count"], "net_pnl": stressed["net_pnl"],
            "max_drawdown_pct": stressed["max_drawdown_pct"],
            "profit_factor": stressed["profit_factor"],
            "rejected_signals": stressed["rejected_signals"],
        })

    completed = [f for f in fold_reports if f["status"] == "completed"]
    pnls = [float(t["net_pnl"]) for t in trades]
    wins, losses = sum(x > 0 for x in pnls), sum(x < 0 for x in pnls)
    gross_profit = sum(x for x in pnls if x > 0)
    gross_loss = -sum(x for x in pnls if x < 0)
    positive_folds = sum(f["net_pnl"] > 0 for f in completed)
    aggregate = {
        "requested_test_folds": folds, "completed_test_folds": len(completed),
        "positive_test_folds": positive_folds,
        "positive_fold_ratio_pct": round(positive_folds / folds * 100, 6),
        "trade_count": len(pnls), "wins": wins, "losses": losses,
        "win_rate_pct": round(wins / len(pnls) * 100, 6) if pnls else None,
        "net_pnl": round(sum(pnls), 8),
        "profit_factor": round(gross_profit / gross_loss, 8) if gross_loss else ("infinite" if gross_profit else None),
        "expectancy_per_trade": round(sum(pnls) / len(pnls), 8) if pnls else None,
        "trade_sequence_max_drawdown_pct": None,
        "drawdown_scope": "not_aggregated_across_independent_folds",
    }
    stress_completed = [f for f in stress_reports if f["status"] == "completed"]
    stress_dd = [f["max_drawdown_pct"] for f in stress_completed if f["max_drawdown_pct"] is not None]
    stress = {
        "status": "completed" if stress_completed else "insufficient_data",
        "cost_multiplier": stress_cost_multiplier,
        "fold_execution_count": len(stress_completed), "folds": stress_reports,
        "pooled_net_pnl": round(sum(float(t["net_pnl"]) for t in stress_trades), 8),
        "worst_fold_max_drawdown_pct": round(max(stress_dd), 8) if stress_dd else None,
        "execution_allowed": False,
    }
    return {
        "status": "completed" if completed else "insufficient_data",
        "validation_type": "rolling_walk_forward_oos_replay",
        "mode": "historical_research", "folds": fold_reports,
        "aggregate_oos": aggregate,
        "monte_carlo": _wf_mc(pnls, monte_carlo_simulations, random_seed, initial_equity),
        "execution_cost_stress": stress, "estimated_win_probability": None,
        "methodology": {
            "optimization": "Parameter optimization is not performed; fixed caller-supplied signals are replayed on chronological out-of-sample windows.",
            "fold_design": "Chronological disjoint timestamp windows with independently reset equity.",
            "signal_selection": "Signal decision and its following entry candle must both fall inside the same OOS window.",
            "monte_carlo": "Descriptive bootstrap resampling, not a forecast.",
        },
        "limitations": [
            "Signals are caller-supplied; this endpoint cannot independently verify causal signal generation.",
            "No parameter optimization, walk-forward fitting, or multiple-testing correction is performed.",
            "Independent folds reset equity; pooled PnL is not a compounded equity curve.",
            "The OHLC engine assumes stop-loss before target when both are touched in one candle.",
            "Broker margin, leverage, funding, liquidation, order-book depth, latency and live fills are not modeled.",
            "Monte Carlo resampling does not model serial dependence or future market regimes.",
            "Research diagnostics only; no profitability guarantee or live-readiness certification.",
        ],
        "execution_allowed": False,
    }

