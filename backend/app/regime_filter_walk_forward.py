from __future__ import annotations

import math
from typing import Any

from .historical_smc_backtest import run_historical_smc_portfolio_backtest
from .regime_filter_evaluation import _metrics, _regime_breakdown


def evaluate_regime_filter_walk_forward(
    candles_by_symbol_and_tf: dict[str, dict[str, list[dict[str, Any]]]],
    *,
    initial_train_fraction: float = 0.50,
    oos_fraction: float = 0.10,
    step_fraction: float = 0.10,
    max_folds: int = 5,
    initial_equity: float = 10_000.0,
    risk_percent: float = 0.5,
    min_quality_score: int = 65,
    min_rr: float = 2.0,
    allow_counter_trend: bool = False,
    max_signals_per_symbol: int = 500,
    history_limit: int = 500,
    spread: float = 0.0,
    slippage: float = 0.0,
    commission_pct: float = 0.0,
    max_open_trades: int = 3,
    max_daily_loss_pct: float = 3.0,
    max_weekly_loss_pct: float = 6.0,
    max_drawdown_pct: float = 15.0,
    reject_transition_regime: bool = True,
    require_trend_alignment: bool = True,
    reject_high_volatility: bool = False,
) -> dict[str, Any]:
    """Run expanding-window, sequential OOS folds for baseline vs regime filter.

    Each fold has its own portfolio reset. Historical candles before the fold
    remain available only for causal warm-up; trades are replayed within that
    fold's OOS interval and are closed at the interval end.
    """
    if not isinstance(candles_by_symbol_and_tf, dict) or not candles_by_symbol_and_tf:
        raise ValueError("candles_by_symbol_and_tf must not be empty")
    for name, value, lower, upper in (
        ("initial_train_fraction", initial_train_fraction, 0.30, 0.80),
        ("oos_fraction", oos_fraction, 0.05, 0.30),
        ("step_fraction", step_fraction, 0.05, 0.30),
    ):
        if not math.isfinite(float(value)) or not lower <= float(value) <= upper:
            raise ValueError(f"{name} must be between {lower} and {upper}")
    if not isinstance(max_folds, int) or not 2 <= max_folds <= 10:
        raise ValueError("max_folds must be between 2 and 10")

    timelines: dict[str, list[dict[str, Any]]] = {}
    lengths = set()
    for raw_symbol, tf_data in candles_by_symbol_and_tf.items():
        if not isinstance(tf_data, dict) or not isinstance(tf_data.get("5m"), list):
            raise ValueError(f"Missing 5m candles for {raw_symbol}")
        rows = tf_data["5m"]
        if len(rows) < 200:
            raise ValueError(f"At least 200 5m candles are required for {raw_symbol}")
        timelines[str(raw_symbol).strip().upper()] = rows
        lengths.add(len(rows))
    if len(lengths) != 1:
        raise ValueError("All symbols must have the same 5m candle count")

    count = next(iter(lengths))
    reference_times = [int(row["time"]) for row in next(iter(timelines.values()))]
    for symbol, rows in timelines.items():
        if [int(row["time"]) for row in rows] != reference_times:
            raise ValueError("All symbols must have identical aligned 5m timestamps")

    possible_folds = 0
    probe_fraction = float(initial_train_fraction)
    while possible_folds < max_folds and probe_fraction + float(oos_fraction) <= 1.0 + 1e-9:
        possible_folds += 1
        probe_fraction += float(step_fraction)
    if possible_folds < 2:
        raise ValueError("The supplied history cannot produce at least two OOS folds")

    common = dict(
        initial_equity=initial_equity,
        risk_percent=risk_percent,
        min_quality_score=min_quality_score,
        min_rr=min_rr,
        allow_counter_trend=allow_counter_trend,
        max_signals_per_symbol=max_signals_per_symbol,
        history_limit=history_limit,
        spread=spread,
        slippage=slippage,
        commission_pct=commission_pct,
        max_open_trades=max_open_trades,
        max_daily_loss_pct=max_daily_loss_pct,
        max_weekly_loss_pct=max_weekly_loss_pct,
        max_drawdown_pct=max_drawdown_pct,
    )

    folds: list[dict[str, Any]] = []
    all_base_trades: list[dict[str, Any]] = []
    all_filtered_trades: list[dict[str, Any]] = []
    start_fraction = float(initial_train_fraction)

    for fold_number in range(max_folds):
        end_fraction = start_fraction + float(oos_fraction)
        if end_fraction > 1.0 + 1e-9:
            break
        start_index = int(count * start_fraction)
        end_index = min(count - 1, int(count * end_fraction))
        if start_index < 50 or end_index - start_index < 10:
            raise ValueError("Each OOS fold must contain at least 10 5m intervals")
        start_time = reference_times[start_index] + 300
        end_time = reference_times[end_index] + 300
        if end_time <= start_time:
            raise ValueError("Invalid OOS fold boundaries")

        baseline = run_historical_smc_portfolio_backtest(
            candles_by_symbol_and_tf,
            **common,
            use_regime_filter=False,
            signal_time_start=start_time,
            signal_time_end=end_time,
        )
        filtered = run_historical_smc_portfolio_backtest(
            candles_by_symbol_and_tf,
            **common,
            use_regime_filter=True,
            reject_transition_regime=reject_transition_regime,
            require_trend_alignment=require_trend_alignment,
            reject_high_volatility=reject_high_volatility,
            signal_time_start=start_time,
            signal_time_end=end_time,
        )
        base_trades = baseline.get("trades", [])
        filtered_trades = filtered.get("trades", [])
        all_base_trades.extend(base_trades)
        all_filtered_trades.extend(filtered_trades)

        bm = _metrics(base_trades)
        fm = _metrics(filtered_trades)
        folds.append({
            "fold": fold_number + 1,
            "train_end_fraction": round(start_fraction, 4),
            "oos_end_fraction": round(end_fraction, 4),
            "oos_start_time": start_time,
            "oos_end_time_exclusive": end_time,
            "baseline": {
                "metrics": bm,
                "max_drawdown_pct": baseline.get("max_drawdown_pct"),
                "regime_breakdown": _regime_breakdown(base_trades),
                "trade_count": len(base_trades),
            },
            "regime_filtered": {
                "metrics": fm,
                "max_drawdown_pct": filtered.get("max_drawdown_pct"),
                "regime_breakdown": _regime_breakdown(filtered_trades),
                "trade_count": len(filtered_trades),
                "filter_rejections": sum(
                    int(result.get("rejected_counts", {}).get("regime_filter", 0))
                    for result in filtered.get("signal_generation", {}).values()
                ),
            },
            "delta_filtered_minus_baseline": {
                "net_pnl": round(fm["net_pnl"] - bm["net_pnl"], 8),
                "win_rate_pct": (
                    round(fm["win_rate_pct"] - bm["win_rate_pct"], 4)
                    if fm["win_rate_pct"] is not None and bm["win_rate_pct"] is not None else None
                ),
                "expectancy_per_trade": (
                    round(fm["expectancy_per_trade"] - bm["expectancy_per_trade"], 8)
                    if fm["expectancy_per_trade"] is not None and bm["expectancy_per_trade"] is not None else None
                ),
            },
        })
        start_fraction += float(step_fraction)

    if len(folds) < 2:
        raise ValueError("The supplied history cannot produce at least two OOS folds")

    base_total = _metrics(all_base_trades)
    filtered_total = _metrics(all_filtered_trades)
    profitable_filtered_folds = sum(
        1 for fold in folds
        if fold["regime_filtered"]["metrics"]["net_pnl"] > 0
    )
    profitable_baseline_folds = sum(
        1 for fold in folds
        if fold["baseline"]["metrics"]["net_pnl"] > 0
    )

    return {
        "status": "completed",
        "evaluation": "expanding_window_walk_forward",
        "fold_count": len(folds),
        "folds": folds,
        "aggregate": {
            "baseline": {
                "metrics": base_total,
                "profitable_fold_count": profitable_baseline_folds,
                "max_fold_drawdown_pct": max(
                    (fold["baseline"]["max_drawdown_pct"] or 0.0 for fold in folds),
                    default=0.0,
                ),
            },
            "regime_filtered": {
                "metrics": filtered_total,
                "profitable_fold_count": profitable_filtered_folds,
                "max_fold_drawdown_pct": max(
                    (fold["regime_filtered"]["max_drawdown_pct"] or 0.0 for fold in folds),
                    default=0.0,
                ),
            },
            "delta_filtered_minus_baseline": {
                "net_pnl": round(filtered_total["net_pnl"] - base_total["net_pnl"], 8),
                "win_rate_pct": (
                    round(filtered_total["win_rate_pct"] - base_total["win_rate_pct"], 4)
                    if filtered_total["win_rate_pct"] is not None and base_total["win_rate_pct"] is not None else None
                ),
                "expectancy_per_trade": (
                    round(filtered_total["expectancy_per_trade"] - base_total["expectancy_per_trade"], 8)
                    if filtered_total["expectancy_per_trade"] is not None and base_total["expectancy_per_trade"] is not None else None
                ),
            },
        },
        "cost_model": {
            "spread_price_units": spread,
            "slippage_price_units": slippage,
            "commission_pct": commission_pct,
        },
        "methodology": {
            "window": "expanding_training_then_non_overlapping_or_stepped_oos",
            "portfolio_reset_per_fold": True,
            "warmup_uses_only_history_available_before_each_decision": True,
            "oos_end_forced_close": True,
            "parameter_optimization": False,
        },
        "limitations": [
            "Fold PnL is reported per independently reset portfolio; aggregate PnL sums fold results and is not a continuous compounded equity curve.",
            "No parameter tuning is performed; the regime policy is evaluated as specified.",
            "A minimum of two folds and aligned symbol timestamps are required.",
            "Historical performance does not establish future profitability.",
        ],
        "execution_allowed": False,
    }
