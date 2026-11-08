from __future__ import annotations

import math
from typing import Any

from .historical_smc_backtest import run_historical_smc_portfolio_backtest


def _metrics(trades: list[dict[str, Any]]) -> dict[str, Any]:
    pnls = [float(t.get("net_pnl", 0.0)) for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    return {
        "trade_count": len(pnls),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate_pct": round(len(wins) / len(pnls) * 100, 4) if pnls else None,
        "net_pnl": round(sum(pnls), 8),
        "profit_factor": round(gross_profit / gross_loss, 6) if gross_loss else ("infinite" if wins else None),
        "expectancy_per_trade": round(sum(pnls) / len(pnls), 8) if pnls else None,
    }


def _regime_breakdown(trades: list[dict[str, Any]]) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for trade in trades:
        context = trade.get("market_regime") or {}
        regime = str(context.get("aggregate_regime", "unknown"))
        groups.setdefault(regime, []).append(trade)
    return {regime: _metrics(items) for regime, items in sorted(groups.items())}


def evaluate_regime_filter_oos(
    candles_by_symbol_and_tf: dict[str, dict[str, list[dict[str, Any]]]],
    *,
    train_fraction: float = 0.70,
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
    """Compare baseline and regime-filtered SMC on a chronological OOS segment.

    All historical candles remain available as causal warm-up. Only signals whose
    decision time is at/after the per-symbol OOS boundary are replayed. The split
    is derived from each symbol's 5m timeline; portfolio replay remains shared.
    """
    if not isinstance(candles_by_symbol_and_tf, dict) or not candles_by_symbol_and_tf:
        raise ValueError("candles_by_symbol_and_tf must not be empty")
    if not math.isfinite(float(train_fraction)) or not 0.5 <= float(train_fraction) <= 0.9:
        raise ValueError("train_fraction must be between 0.5 and 0.9")

    cutoffs: dict[str, int] = {}
    for raw_symbol, tf_data in candles_by_symbol_and_tf.items():
        rows = tf_data.get("5m") if isinstance(tf_data, dict) else None
        if not isinstance(rows, list) or len(rows) < 100:
            raise ValueError(f"At least 100 5m candles are required for {raw_symbol}")
        split_index = int(len(rows) * float(train_fraction))
        if split_index < 50 or split_index >= len(rows) - 1:
            raise ValueError(f"Invalid OOS split for {raw_symbol}")
        # Signal timestamps denote the close/decision time of the 5m candle.
        cutoffs[str(raw_symbol).strip().upper()] = int(rows[split_index]["time"]) + 300

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

    # Each symbol has its own chronological boundary. The portfolio API accepts
    # one timestamp boundary, so mixed boundaries are not silently approximated.
    if len(set(cutoffs.values())) != 1:
        raise ValueError(
            "Symbols must share the same 5m OOS cutoff timestamp; evaluate symbols "
            "with aligned histories or run them separately."
        )
    cutoff = next(iter(cutoffs.values()))

    baseline = run_historical_smc_portfolio_backtest(
        candles_by_symbol_and_tf,
        **common,
        use_regime_filter=False,
        signal_time_start=cutoff,
    )
    filtered = run_historical_smc_portfolio_backtest(
        candles_by_symbol_and_tf,
        **common,
        use_regime_filter=True,
        reject_transition_regime=reject_transition_regime,
        require_trend_alignment=require_trend_alignment,
        reject_high_volatility=reject_high_volatility,
        signal_time_start=cutoff,
    )

    baseline_trades = baseline.get("trades", [])
    filtered_trades = filtered.get("trades", [])
    baseline_metrics = _metrics(baseline_trades)
    filtered_metrics = _metrics(filtered_trades)

    def delta(key: str) -> float | None:
        a, b = baseline_metrics.get(key), filtered_metrics.get(key)
        if a is None or b is None or not isinstance(a, (int, float)) or not isinstance(b, (int, float)):
            return None
        return round(float(b) - float(a), 8)

    return {
        "status": "completed",
        "evaluation": "chronological_out_of_sample",
        "oos_cutoff_time": cutoff,
        "train_fraction": float(train_fraction),
        "baseline": {
            "metrics": baseline_metrics,
            "max_drawdown_pct": baseline.get("max_drawdown_pct"),
            "regime_breakdown": _regime_breakdown(baseline_trades),
            "generated_signal_count": baseline.get("generated_signal_count", 0),
            "rejected_by_risk_controls": len(baseline.get("rejected_signals", [])),
        },
        "regime_filtered": {
            "metrics": filtered_metrics,
            "max_drawdown_pct": filtered.get("max_drawdown_pct"),
            "regime_breakdown": _regime_breakdown(filtered_trades),
            "generated_signal_count": filtered.get("generated_signal_count", 0),
            "rejected_by_risk_controls": len(filtered.get("rejected_signals", [])),
            "filter_rejections": sum(
                int(result.get("rejected_counts", {}).get("regime_filter", 0))
                for result in filtered.get("signal_generation", {}).values()
            ),
        },
        "delta_filtered_minus_baseline": {
            "net_pnl": delta("net_pnl"),
            "win_rate_pct": delta("win_rate_pct"),
            "expectancy_per_trade": delta("expectancy_per_trade"),
        },
        "cost_model": {
            "spread_price_units": spread,
            "slippage_price_units": slippage,
            "commission_pct": commission_pct,
        },
        "limitations": [
            "This is one chronological holdout, not repeated walk-forward validation.",
            "A single common cutoff is required for all symbols in a shared portfolio.",
            "No parameter optimization is performed on the OOS segment.",
            "Results are historical research and do not imply future profitability.",
        ],
        "execution_allowed": False,
    }
