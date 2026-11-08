from __future__ import annotations

import math
import random
from statistics import mean
from typing import Any

from .multi_backtesting import run_multi_symbol_backtest


def _finite(value: Any, name: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{name} must be numeric") from exc
    if not math.isfinite(result):
        raise ValueError(f"{name} must be finite")
    return result


def _max_drawdown(values: list[float]) -> float:
    peak = values[0] if values else 0.0
    worst = 0.0
    for value in values:
        peak = max(peak, value)
        if peak > 0:
            worst = max(worst, (peak - value) / peak * 100.0)
    return worst


def _trade_metrics(
    trades: list[dict[str, Any]],
    initial_equity: float = 10_000.0,
    *,
    calculate_sequence_drawdown: bool = True,
) -> dict[str, Any]:
    pnls = [_finite(t.get("net_pnl"), "trade net_pnl") for t in trades]
    wins = [x for x in pnls if x > 0]
    losses = [x for x in pnls if x < 0]
    gp, gl = sum(wins), abs(sum(losses))
    result = {
        "trade_count": len(pnls),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate_pct": round(len(wins) / len(pnls) * 100, 4) if pnls else None,
        "net_pnl": round(sum(pnls), 8),
        "expectancy_per_trade": round(mean(pnls), 8) if pnls else None,
        "profit_factor": round(gp / gl, 6) if gl else ("infinite" if gp else None),
    }
    if calculate_sequence_drawdown:
        equity = float(initial_equity)
        curve = [equity]
        for pnl in pnls:
            equity += pnl
            curve.append(equity)
        result["trade_sequence_max_drawdown_pct"] = round(_max_drawdown(curve), 6)
        result["drawdown_scope"] = "single_independent_fold_trade_sequence"
    else:
        # Fold portfolios restart from initial_equity. Concatenating their PnLs
        # does not produce a valid single-account equity curve.
        result["trade_sequence_max_drawdown_pct"] = None
        result["drawdown_scope"] = "not_aggregated_across_independent_folds"
    return result


def _monte_carlo(
    trades: list[dict[str, Any]],
    *,
    initial_equity: float,
    simulations: int,
    seed: int,
) -> dict[str, Any]:
    pnls = [_finite(t.get("net_pnl"), "trade net_pnl") for t in trades]
    if len(pnls) < 10:
        return {
            "status": "insufficient_data",
            "trade_count": len(pnls),
            "minimum_trades_recommended": 10,
            "reason": "At least 10 out-of-sample trades are required; 100+ is preferable.",
        }
    rng = random.Random(seed)
    ending_returns: list[float] = []
    drawdowns: list[float] = []
    ruin_count = 0
    n = len(pnls)
    for _ in range(simulations):
        equity = float(initial_equity)
        peak = equity
        worst = 0.0
        for _ in range(n):
            equity += rng.choice(pnls)
            peak = max(peak, equity)
            if peak > 0:
                worst = max(worst, (peak - equity) / peak * 100.0)
        ending_returns.append((equity / initial_equity - 1.0) * 100.0)
        drawdowns.append(worst)
        if equity <= 0:
            ruin_count += 1
    ending_returns.sort()
    drawdowns.sort()

    def percentile(values: list[float], p: float) -> float:
        index = (len(values) - 1) * p
        lo, hi = math.floor(index), math.ceil(index)
        if lo == hi:
            return values[lo]
        return values[lo] * (hi - index) + values[hi] * (index - lo)

    return {
        "status": "completed",
        "method": "trade_pnl_bootstrap_with_replacement",
        "simulations": simulations,
        "seed": seed,
        "trade_count_per_path": n,
        "ending_return_pct": {
            "p05": round(percentile(ending_returns, .05), 4),
            "median": round(percentile(ending_returns, .50), 4),
            "p95": round(percentile(ending_returns, .95), 4),
        },
        "max_drawdown_pct": {
            "p50": round(percentile(drawdowns, .50), 4),
            "p95": round(percentile(drawdowns, .95), 4),
            "p99": round(percentile(drawdowns, .99), 4),
        },
        "probability_of_equity_depletion_pct": round(ruin_count / simulations * 100, 4),
        "limitations": [
            "Resamples observed trade PnL in fixed currency units; it does not model dynamic position sizing.",
            "Trade dependence, regime changes, liquidity and market impact are not fully represented.",
            "This is a robustness diagnostic, not a forecast or win-probability estimate.",
        ],
    }


def validate_strategy_walk_forward(
    candles_by_symbol: dict[str, list[dict[str, Any]]],
    signals: list[dict[str, Any]],
    *,
    initial_equity: float = 10_000.0,
    spread: float = 0.0,
    slippage: float = 0.0,
    commission_pct: float = 0.0,
    max_open_trades: int = 3,
    max_daily_loss_pct: float = 3.0,
    max_weekly_loss_pct: float = 6.0,
    max_drawdown_pct: float = 15.0,
    folds: int = 4,
    monte_carlo_simulations: int = 1000,
    random_seed: int = 42,
    stress_cost_multiplier: float = 2.0,
) -> dict[str, Any]:
    """Chronological rolling OOS replay for externally generated signals.

    Every OOS fold is independently replayed from initial_equity. Signals are
    supplied by the caller and are not regenerated or optimized in each fold.
    """
    if not isinstance(candles_by_symbol, dict) or not candles_by_symbol:
        raise ValueError("candles_by_symbol must not be empty")
    if not isinstance(signals, list):
        raise ValueError("signals must be a list")
    if not isinstance(folds, int) or not 2 <= folds <= 10:
        raise ValueError("folds must be between 2 and 10")
    if not isinstance(monte_carlo_simulations, int) or not 100 <= monte_carlo_simulations <= 5000:
        raise ValueError("monte_carlo_simulations must be between 100 and 5000")
    if not isinstance(random_seed, int) or not 0 <= random_seed <= 2**32 - 1:
        raise ValueError("random_seed must be an unsigned 32-bit integer")

    initial_equity = _finite(initial_equity, "initial_equity")
    if initial_equity <= 0:
        raise ValueError("initial_equity must be positive")
    spread = _finite(spread, "spread")
    slippage = _finite(slippage, "slippage")
    commission_pct = _finite(commission_pct, "commission_pct")
    if spread < 0 or slippage < 0 or not 0 <= commission_pct <= 5:
        raise ValueError("Trading costs must be nonnegative and commission_pct cannot exceed 5")
    for name, value in (
        ("max_daily_loss_pct", max_daily_loss_pct),
        ("max_weekly_loss_pct", max_weekly_loss_pct),
        ("max_drawdown_pct", max_drawdown_pct),
    ):
        value = _finite(value, name)
        if not 0 <= value <= 100:
            raise ValueError(f"{name} must be between 0 and 100")

    stress_cost_multiplier = _finite(stress_cost_multiplier, "stress_cost_multiplier")
    if not 1 <= stress_cost_multiplier <= 10:
        raise ValueError("stress_cost_multiplier must be between 1 and 10")
    if commission_pct * stress_cost_multiplier > 5:
        raise ValueError("commission_pct multiplied by stress_cost_multiplier cannot exceed 5")

    normalized: dict[str, list[dict[str, Any]]] = {}
    timeline: set[int] = set()
    for raw_symbol, rows in candles_by_symbol.items():
        symbol = str(raw_symbol).strip().upper()
        if not symbol or symbol in normalized or not isinstance(rows, list) or len(rows) < 3:
            raise ValueError(f"Invalid candle series for {raw_symbol}")
        normalized[symbol] = rows
        previous = None
        for row in rows:
            try:
                ts = int(row["time"])
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError(f"Invalid candle timestamp for {symbol}") from exc
            if previous is not None and ts <= previous:
                raise ValueError(f"Candles for {symbol} must be strictly chronological")
            previous = ts
            timeline.add(ts)

    ordered = sorted(timeline)
    if len(ordered) < folds + 2:
        raise ValueError("Not enough distinct timestamps for requested walk-forward folds")
    boundaries = [ordered[(i * len(ordered)) // (folds + 1)] for i in range(folds + 1)]
    boundaries.append(ordered[-1] + 1)

    signal_rows: list[dict[str, Any]] = []
    for raw in signals:
        try:
            symbol = str(raw["symbol"]).strip().upper()
            idx = int(raw["index"])
            if symbol not in normalized or idx < 0 or idx >= len(normalized[symbol]) - 1:
                raise ValueError("Signal references an invalid symbol/index")
            signal_rows.append({
                **raw,
                "symbol": symbol,
                "index": idx,
                "_signal_time": int(normalized[symbol][idx]["time"]),
                "_entry_time": int(normalized[symbol][idx + 1]["time"]),
            })
        except (KeyError, TypeError, ValueError, IndexError) as exc:
            raise ValueError("Invalid signal in walk-forward input") from exc

    fold_reports: list[dict[str, Any]] = []
    all_oos_trades: list[dict[str, Any]] = []
    stress_fold_reports: list[dict[str, Any]] = []

    for fold_index in range(folds):
        start, end_exclusive = boundaries[fold_index + 1], boundaries[fold_index + 2]
        fold_signals = [
            s for s in signal_rows
            if start <= s["_signal_time"] < end_exclusive and s["_entry_time"] < end_exclusive
        ]
        base_report = {
            "fold": fold_index + 1,
            "training_history_start": ordered[0],
            "training_history_end": start - 1,
            "test_start": start,
            "test_end": end_exclusive - 1,
        }
        if not fold_signals:
            fold_reports.append({
                **base_report,
                "status": "no_test_signals",
                "signals_tested": 0,
                "metrics": _trade_metrics([], initial_equity),
            })
            continue

        # Keep the full prefix for indicator/history context, but never include
        # bars at or beyond the fold's exclusive test end.
        fold_candles = {
            symbol: [c for c in rows if int(c["time"]) < end_exclusive]
            for symbol, rows in normalized.items()
        }
        fold_candles = {symbol: rows for symbol, rows in fold_candles.items() if len(rows) >= 3}
        valid_signals = [s for s in fold_signals if s["symbol"] in fold_candles]
        payload_signals = [
            {k: v for k, v in s.items() if not k.startswith("_")}
            for s in valid_signals
        ]
        if not payload_signals:
            fold_reports.append({
                **base_report,
                "status": "no_eligible_signals",
                "signals_tested": 0,
                "metrics": _trade_metrics([], initial_equity),
            })
            continue

        result = run_multi_symbol_backtest(
            fold_candles,
            payload_signals,
            initial_equity=initial_equity,
            spread=spread,
            slippage=slippage,
            commission_pct=commission_pct,
            max_open_trades=max_open_trades,
            max_daily_loss_pct=max_daily_loss_pct,
            max_weekly_loss_pct=max_weekly_loss_pct,
            max_drawdown_pct=max_drawdown_pct,
        )
        trades = result["trades"]
        all_oos_trades.extend(trades)
        fold_reports.append({
            **base_report,
            "status": "completed",
            "signals_tested": len(payload_signals),
            "metrics": _trade_metrics(trades, initial_equity),
        })

        # Stress each fold independently, using exactly the same fold boundary,
        # signal set, portfolio reset and risk limits as its baseline replay.
        stress_result = run_multi_symbol_backtest(
            fold_candles,
            payload_signals,
            initial_equity=initial_equity,
            spread=spread * stress_cost_multiplier,
            slippage=slippage * stress_cost_multiplier,
            commission_pct=commission_pct * stress_cost_multiplier,
            max_open_trades=max_open_trades,
            max_daily_loss_pct=max_daily_loss_pct,
            max_weekly_loss_pct=max_weekly_loss_pct,
            max_drawdown_pct=max_drawdown_pct,
        )
        stress_fold_reports.append({
            "fold": fold_index + 1,
            "trade_count": stress_result["trade_count"],
            "net_pnl": stress_result["net_pnl"],
            "max_drawdown_pct": stress_result["max_drawdown_pct"],
            "profit_factor": stress_result["profit_factor"],
        })

    aggregate = _trade_metrics(
        all_oos_trades,
        initial_equity,
        calculate_sequence_drawdown=False,
    )
    warnings: list[str] = []
    if aggregate["trade_count"] < 30:
        warnings.append("Fewer than 30 OOS trades: performance estimates are statistically fragile.")
    if aggregate["trade_count"] < 100:
        warnings.append("Prefer 100+ OOS trades across multiple market regimes before relying on results.")

    completed = [f for f in fold_reports if f["status"] == "completed"]
    positive_folds = sum(1 for f in completed if (f["metrics"]["net_pnl"] or 0) > 0)
    aggregate["positive_test_folds"] = positive_folds
    aggregate["completed_test_folds"] = len(completed)
    aggregate["requested_test_folds"] = folds
    aggregate["fold_coverage_pct"] = round(len(completed) / folds * 100, 2)
    # Empty/no-trade folds are not silently removed from the consistency denominator.
    aggregate["positive_fold_ratio_pct"] = round(positive_folds / folds * 100, 2)

    mc = _monte_carlo(
        all_oos_trades,
        initial_equity=initial_equity,
        simulations=monte_carlo_simulations,
        seed=random_seed,
    )

    stress = None
    if stress_fold_reports:
        stress_trades = sum(item["trade_count"] for item in stress_fold_reports)
        stress_net_pnl = round(sum(item["net_pnl"] for item in stress_fold_reports), 8)
        stress_dds = [item["max_drawdown_pct"] for item in stress_fold_reports]
        stress = {
            "cost_multiplier": stress_cost_multiplier,
            "trade_count": stress_trades,
            "net_pnl": stress_net_pnl,
            "worst_fold_max_drawdown_pct": max(stress_dds) if stress_dds else None,
            "folds": stress_fold_reports,
            "fold_execution_count": len(stress_fold_reports),
            "note": "Each fold is stress-replayed independently with the same OOS signals and initial-equity reset as baseline.",
        }

    return {
        "validation_type": "rolling_walk_forward_oos_replay",
        "status": "completed" if completed else "insufficient_oos_signals",
        "fold_count_requested": folds,
        "initial_history_period": {"start": ordered[0], "end": boundaries[1] - 1},
        "folds": fold_reports,
        "aggregate_oos": aggregate,
        "monte_carlo": mc,
        "execution_cost_stress": stress,
        "warnings": warnings,
        "methodology": {
            "folding": "First chronological block is reserved as initial history; following blocks are contiguous OOS test folds.",
            "capital": "Each fold is independently replayed from initial_equity; aggregate OOS trade PnL is not a single continuously compounded portfolio curve.",
            "aggregate_drawdown": "No single aggregate trade-sequence drawdown is reported because fold equity resets independently; inspect per-fold drawdown and Monte Carlo drawdown diagnostics.",
            "fold_consistency": "Positive-fold ratio uses all requested test folds as denominator; folds without eligible trades are not silently excluded.",
            "signal_generation": "Signals are supplied by the caller and are not retrained or regenerated inside each fold.",
            "optimization": "Parameter optimization is not performed. A true walk-forward optimizer requires a strategy function and trainable parameter space.",
            "leakage_warning": "Ensure supplied historical signals were generated without using candles after their signal timestamp.",
            "monte_carlo": "Bootstrap of pooled OOS trade PnL in fixed currency units; it does not preserve fold boundaries or trade dependence and is not a predictive probability model.",
        },
        "estimated_win_probability": None,
        "execution_allowed": False,
    }
