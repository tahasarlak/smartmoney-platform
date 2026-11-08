from __future__ import annotations

import math
from typing import Any, Callable

from .historical_smc_backtest import run_historical_smc_portfolio_backtest
from .regime_filter_evaluation import _metrics


def _trade_risk_stats(trades: list[dict[str, Any]]) -> dict[str, Any]:
    pnls = [float(item.get("net_pnl", 0.0)) for item in trades]
    equity = 0.0
    peak = 0.0
    max_drawdown = 0.0
    max_losing_streak = 0
    losing_streak = 0
    for pnl in pnls:
        equity += pnl
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, peak - equity)
        if pnl < 0:
            losing_streak += 1
            max_losing_streak = max(max_losing_streak, losing_streak)
        else:
            losing_streak = 0
    gross_profit = sum(value for value in pnls if value > 0)
    gross_loss = abs(sum(value for value in pnls if value < 0))
    return {
        "max_consecutive_losses": max_losing_streak,
        "max_trade_sequence_drawdown": round(max_drawdown, 8),
        "gross_profit": round(gross_profit, 8),
        "gross_loss": round(gross_loss, 8),
        "recovery_factor": (
            round(sum(pnls) / max_drawdown, 6) if max_drawdown > 0 else None
        ),
    }


def evaluate_execution_cost_stress(
    candles_by_symbol_and_tf: dict[str, dict[str, list[dict[str, Any]]]],
    *,
    cost_scenarios: list[dict[str, float]] | None = None,
    use_regime_filter: bool = True,
    initial_equity: float = 10_000.0,
    risk_percent: float = 0.5,
    min_quality_score: int = 65,
    min_rr: float = 2.0,
    allow_counter_trend: bool = False,
    max_signals_per_symbol: int = 500,
    history_limit: int = 500,
    max_open_trades: int = 3,
    max_daily_loss_pct: float = 3.0,
    max_weekly_loss_pct: float = 6.0,
    max_drawdown_pct: float = 15.0,
    signal_time_start: int | None = None,
    signal_time_end: int | None = None,
    reject_transition_regime: bool = True,
    require_trend_alignment: bool = True,
    reject_high_volatility: bool = False,
) -> dict[str, Any]:
    """Replay identical strategy settings under progressively harsher cost assumptions.

    This is a deterministic sensitivity analysis, not a forecast or Monte Carlo
    probability estimate. Costs are expressed in the backtest's existing units.
    """
    if not isinstance(candles_by_symbol_and_tf, dict) or not candles_by_symbol_and_tf:
        raise ValueError("candles_by_symbol_and_tf must not be empty")
    if cost_scenarios is None:
        cost_scenarios = [
            {"name": "base", "spread": 0.0, "slippage": 0.0, "commission_pct": 0.0},
            {"name": "moderate", "spread": 0.5, "slippage": 0.25, "commission_pct": 0.05},
            {"name": "stressed", "spread": 1.0, "slippage": 0.5, "commission_pct": 0.10},
            {"name": "severe", "spread": 2.0, "slippage": 1.0, "commission_pct": 0.20},
        ]
    if not isinstance(cost_scenarios, list) or not 2 <= len(cost_scenarios) <= 10:
        raise ValueError("cost_scenarios must contain between 2 and 10 scenarios")

    normalized_scenarios: list[dict[str, Any]] = []
    seen_names: set[str] = set()
    for raw in cost_scenarios:
        if not isinstance(raw, dict):
            raise ValueError("Each cost scenario must be a dictionary")
        name = str(raw.get("name", "")).strip()
        if not name or name in seen_names:
            raise ValueError("Each cost scenario needs a unique non-empty name")
        seen_names.add(name)
        values: dict[str, float] = {}
        for field in ("spread", "slippage", "commission_pct"):
            try:
                value = float(raw[field])
            except (KeyError, TypeError, ValueError, OverflowError) as exc:
                raise ValueError(f"Scenario {name} requires numeric {field}") from exc
            if not math.isfinite(value) or value < 0:
                raise ValueError(f"Scenario {name} has invalid {field}")
            if field == "commission_pct" and value > 5:
                raise ValueError("commission_pct cannot exceed 5")
            values[field] = value
        normalized_scenarios.append({"name": name, **values})

    common = dict(
        initial_equity=initial_equity,
        risk_percent=risk_percent,
        min_quality_score=min_quality_score,
        min_rr=min_rr,
        allow_counter_trend=allow_counter_trend,
        max_signals_per_symbol=max_signals_per_symbol,
        history_limit=history_limit,
        max_open_trades=max_open_trades,
        max_daily_loss_pct=max_daily_loss_pct,
        max_weekly_loss_pct=max_weekly_loss_pct,
        max_drawdown_pct=max_drawdown_pct,
        use_regime_filter=use_regime_filter,
        reject_transition_regime=reject_transition_regime,
        require_trend_alignment=require_trend_alignment,
        reject_high_volatility=reject_high_volatility,
        signal_time_start=signal_time_start,
        signal_time_end=signal_time_end,
    )

    results: list[dict[str, Any]] = []
    for scenario in normalized_scenarios:
        replay = run_historical_smc_portfolio_backtest(
            candles_by_symbol_and_tf,
            **common,
            spread=scenario["spread"],
            slippage=scenario["slippage"],
            commission_pct=scenario["commission_pct"],
        )
        trades = replay.get("trades", [])
        results.append({
            "name": scenario["name"],
            "cost_model": {
                "spread_price_units": scenario["spread"],
                "slippage_price_units": scenario["slippage"],
                "commission_pct": scenario["commission_pct"],
            },
            "metrics": _metrics(trades),
            "max_drawdown_pct": replay.get("max_drawdown_pct"),
            "risk_stats": _trade_risk_stats(trades),
            "generated_signal_count": replay.get("generated_signal_count", 0),
            "executed_trade_count": replay.get("trade_count", len(trades)),
            "rejected_signal_count": len(replay.get("rejected_signals", [])),
            "ending_equity": replay.get("ending_equity"),
        })

    base = results[0]
    baseline_net = base["metrics"]["net_pnl"]
    for item in results:
        item["net_pnl_delta_vs_first_scenario"] = round(
            item["metrics"]["net_pnl"] - baseline_net, 8
        )
        item["return_on_initial_equity_pct"] = (
            round(item["metrics"]["net_pnl"] / float(initial_equity) * 100, 6)
            if initial_equity else None
        )

    return {
        "status": "completed",
        "evaluation": "deterministic_execution_cost_sensitivity",
        "strategy": {
            "regime_filter_enabled": use_regime_filter,
            "risk_percent": risk_percent,
            "min_quality_score": min_quality_score,
            "min_rr": min_rr,
            "signal_time_start": signal_time_start,
            "signal_time_end": signal_time_end,
        },
        "scenario_count": len(results),
        "scenarios": results,
        "interpretation": {
            "reference_scenario": base["name"],
            "best_net_pnl_scenario": max(results, key=lambda x: x["metrics"]["net_pnl"])["name"],
            "worst_net_pnl_scenario": min(results, key=lambda x: x["metrics"]["net_pnl"])["name"],
            "cost_sensitivity": (
                "net PnL declined versus the reference scenario"
                if any(x["metrics"]["net_pnl"] < baseline_net for x in results[1:])
                else "no decline observed versus the reference scenario"
            ),
        },
        "limitations": [
            "Cost values are assumptions in price units and must be calibrated to the traded venue and instrument.",
            "The first supplied scenario is the comparison reference; it is not automatically a realistic zero-cost baseline.",
            "This deterministic stress test does not estimate probabilities or future profitability.",
            "Trade-sequence drawdown is calculated from closed-trade PnL and is not a substitute for intrabar portfolio equity drawdown.",
            "No live execution or order routing is enabled.",
        ],
        "execution_allowed": False,
    }
