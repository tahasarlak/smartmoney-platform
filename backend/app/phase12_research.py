from __future__ import annotations

import math
from collections import defaultdict
from statistics import mean
from typing import Any

from .market_regime import analyze_market_regime
from .multi_backtesting import run_multi_symbol_backtest
from .risk_engine import calculate_risk_position_size, allocate_capital, calculate_correlation_matrix
from .strategy_validation import validate_strategy_walk_forward


def _number(value: Any, name: str, *, minimum: float | None = None,
            maximum: float | None = None) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{name} must be numeric") from exc
    if not math.isfinite(result):
        raise ValueError(f"{name} must be finite")
    if minimum is not None and result < minimum:
        raise ValueError(f"{name} must be >= {minimum}")
    if maximum is not None and result > maximum:
        raise ValueError(f"{name} must be <= {maximum}")
    return result


def _normalize_market(candles_by_symbol: Any) -> dict[str, list[dict[str, Any]]]:
    if not isinstance(candles_by_symbol, dict) or not 1 <= len(candles_by_symbol) <= 30:
        raise ValueError("candles_by_symbol must contain 1..30 symbols")
    normalized: dict[str, list[dict[str, Any]]] = {}
    for raw_symbol, rows in candles_by_symbol.items():
        symbol = str(raw_symbol).strip().upper()
        if not symbol or len(symbol) > 40 or symbol in normalized:
            raise ValueError("Symbols must be unique, non-empty and <=40 characters")
        if not isinstance(rows, list) or len(rows) < 40:
            raise ValueError(f"{symbol} requires at least 40 OHLC candles")
        previous = None
        clean = []
        for index, row in enumerate(rows):
            try:
                ts = int(row["time"])
                o, h, low, close = (float(row[k]) for k in ("open", "high", "low", "close"))
                volume = float(row.get("volume", 0.0))
            except (KeyError, TypeError, ValueError, OverflowError) as exc:
                raise ValueError(f"Invalid OHLCV row for {symbol} at index {index}") from exc
            if previous is not None and ts <= previous:
                raise ValueError(f"{symbol} timestamps must be strictly increasing")
            if not all(math.isfinite(v) and v > 0 for v in (o, h, low, close)):
                raise ValueError(f"{symbol} OHLC values must be finite and positive")
            if not math.isfinite(volume) or volume < 0:
                raise ValueError(f"{symbol} volume must be finite and nonnegative")
            if not low <= min(o, close) <= max(o, close) <= h:
                raise ValueError(f"{symbol} OHLC invariant violated at index {index}")
            clean.append({**row, "time": ts, "open": o, "high": h,
                          "low": low, "close": close, "volume": volume})
            previous = ts
        normalized[symbol] = clean
    return normalized


def _metrics_from_trades(trades: list[dict[str, Any]]) -> dict[str, Any]:
    pnls = [_number(t.get("net_pnl", 0), "net_pnl") for t in trades]
    wins = [x for x in pnls if x > 0]
    losses = [x for x in pnls if x < 0]
    gross_profit, gross_loss = sum(wins), abs(sum(losses))
    equity = 1.0
    peak = 1.0
    max_dd = 0.0
    for pnl in pnls:
        equity += pnl
        peak = max(peak, equity)
        if peak > 0:
            max_dd = max(max_dd, (peak - equity) / peak * 100)
    loss_streak = max_streak = 0
    for pnl in pnls:
        if pnl < 0:
            loss_streak += 1
            max_streak = max(max_streak, loss_streak)
        else:
            loss_streak = 0
    return {
        "trade_count": len(pnls),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate_pct": round(len(wins) / len(pnls) * 100, 4) if pnls else None,
        "net_pnl": round(sum(pnls), 8),
        "expectancy_per_trade": round(mean(pnls), 8) if pnls else None,
        "profit_factor": round(gross_profit / gross_loss, 6) if gross_loss else ("infinite" if gross_profit else None),
        "max_trade_sequence_drawdown_pct": round(max_dd, 6) if pnls else None,
        "max_consecutive_losses": max_streak,
        "average_r_multiple": round(mean([float(t["r_multiple"]) for t in trades if t.get("r_multiple") is not None]), 6)
            if any(t.get("r_multiple") is not None for t in trades) else None,
    }


def _validate_strategies(strategies: Any) -> list[dict[str, Any]]:
    if not isinstance(strategies, list) or not 1 <= len(strategies) <= 8:
        raise ValueError("strategies must contain 1..8 candidate strategies")
    normalized = []
    seen = set()
    for item in strategies:
        if not isinstance(item, dict):
            raise ValueError("Each strategy must be an object")
        strategy_id = str(item.get("strategy_id", "")).strip()
        if not strategy_id or len(strategy_id) > 64 or strategy_id in seen:
            raise ValueError("strategy_id must be unique, non-empty and <=64 characters")
        seen.add(strategy_id)
        signals = item.get("signals", [])
        if not isinstance(signals, list) or len(signals) > 10000:
            raise ValueError(f"{strategy_id}: signals must be a list of at most 10000 items")
        normalized.append({"strategy_id": strategy_id, "name": str(item.get("name") or strategy_id)[:100],
                           "signals": signals})
    return normalized


def _strategy_regime_breakdown(
    candles: dict[str, list[dict[str, Any]]],
    signals: list[dict[str, Any]],
    *,
    initial_equity: float,
    spread: float,
    slippage: float,
    commission_pct: float,
    max_open_trades: int,
) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    unclassified = 0
    for signal in signals:
        try:
            symbol = str(signal["symbol"]).strip().upper()
            idx = int(signal["index"])
            rows = candles[symbol]
            if idx < 31 or idx >= len(rows) - 1:
                unclassified += 1
                continue
            # The next candle is retained as the forming row so the analyzer
            # classifies using candles closed at the signal decision boundary.
            regime = analyze_market_regime(rows[:idx + 2], "signal_context")["regime"]
            groups[regime].append(signal)
        except (KeyError, TypeError, ValueError, IndexError):
            unclassified += 1

    reports = {}
    for regime, selected in sorted(groups.items()):
        replay = run_multi_symbol_backtest(
            candles, selected, initial_equity=initial_equity,
            spread=spread, slippage=slippage, commission_pct=commission_pct,
            max_open_trades=max_open_trades,
        )
        reports[regime] = {
            "signal_count": len(selected),
            "metrics": _metrics_from_trades(replay.get("trades", [])),
            "backtest_rejected_count": len(replay.get("rejected", [])),
        }
    return {
        "by_entry_regime": reports,
        "unclassified_signal_count": unclassified,
        "method": "signal_entry_regime_tag_then_independent_portfolio_replay",
        "limitations": [
            "Each regime bucket is replayed as an independent portfolio from initial equity.",
            "This is descriptive attribution, not a regime-conditioned predictive model.",
            "Regime labels use only candles available at each signal decision boundary.",
        ],
    }


def _latest_regimes(candles: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    result = {}
    for symbol, rows in candles.items():
        try:
            result[symbol] = analyze_market_regime(rows, "5m")
        except ValueError as exc:
            result[symbol] = {"status": "unavailable", "reason": str(exc)}
    return result


def _risk_sensitivity(
    candidates: list[dict[str, Any]], *, equity: float,
    risk_levels: list[float], max_notional_pct: float,
) -> dict[str, Any]:
    if not candidates:
        return {"status": "not_run", "reason": "No risk_candidates supplied", "scenarios": []}
    scenarios = []
    for risk_pct in risk_levels:
        sized = []
        for candidate in candidates:
            direction = str(candidate.get("direction", "")).lower()
            entry = _number(candidate.get("entry"), "candidate entry", minimum=1e-12)
            stop = _number(candidate.get("stop"), "candidate stop", minimum=1e-12)
            if direction not in ("long", "short"):
                raise ValueError("Risk candidate direction must be long or short")
            if (direction == "long" and stop >= entry) or (direction == "short" and stop <= entry):
                raise ValueError("Risk candidate stop is on the wrong side of entry")
            sized.append({
                "symbol": str(candidate.get("symbol", "")).upper(),
                "direction": direction,
                "quality_score": candidate.get("quality_score", 0),
                **calculate_risk_position_size(
                    equity=equity, risk_pct=risk_pct, entry=entry, stop=stop,
                    max_notional_pct=max_notional_pct,
                ),
            })
        scenarios.append({"risk_per_trade_pct": risk_pct, "positions": sized,
                          "aggregate_requested_risk_pct": round(sum(x["risk_pct"] for x in sized), 6)})
    return {
        "status": "completed",
        "scenarios": scenarios,
        "note": "Sizing sensitivity only. No trade is opened and no risk level is automatically selected.",
    }


def _forward_analytics(trades: list[dict[str, Any]]) -> dict[str, Any]:
    if not trades:
        return {"status": "not_run", "reason": "No forward_trades supplied"}
    if len(trades) > 50000:
        raise ValueError("forward_trades cannot exceed 50000 rows")
    normalized = []
    for row in trades:
        if not isinstance(row, dict):
            raise ValueError("Each forward trade must be an object")
        pnl = _number(row.get("net_pnl", row.get("realized_pnl")), "forward trade net_pnl")
        normalized.append({**row, "net_pnl": pnl})
    return {"status": "completed", "source": "caller_supplied_forward_trade_export",
            "metrics": _metrics_from_trades(normalized),
            "symbol_breakdown": {
                symbol: _metrics_from_trades([t for t in normalized if str(t.get("symbol", "")).upper() == symbol])
                for symbol in sorted({str(t.get("symbol", "UNKNOWN")).upper() for t in normalized})
            },
            "limitations": ["Analytics use supplied records and do not query PostgreSQL.",
                            "Open trades and unrealized PnL are not included unless supplied as closed net_pnl records."]}


def _benchmark(candles: dict[str, list[dict[str, Any]]],
               strategy_reports: list[dict[str, Any]], initial_equity: float) -> dict[str, Any]:
    market = {}
    for symbol, rows in candles.items():
        first, last = rows[0]["close"], rows[-2]["close"]
        market[symbol] = round((last / first - 1) * 100, 6)
    reports = []
    for report in strategy_reports:
        aggregate = report["validation"].get("aggregate_oos", {})
        net_pnl = aggregate.get("net_pnl")
        reports.append({
            "strategy_id": report["strategy_id"],
            "oos_net_pnl": net_pnl,
            "oos_net_pnl_pct_of_one_initial_equity": (
                round(float(net_pnl) / initial_equity * 100, 6) if net_pnl is not None else None
            ),
            "market_buy_and_hold_return_pct_by_symbol": market,
            "note": "Strategy OOS PnL pools independently reset folds; this percentage is descriptive and is not directly comparable to compounded buy-and-hold return.",
        })
    return {"market_benchmarks": market, "strategy_comparisons": reports,
            "benchmark_method": "first_close_to_last_closed_close_simple_return",
            "execution_allowed": False}


def run_phase12_research_suite(payload: dict[str, Any]) -> dict[str, Any]:
    """Run the Phase 12 strategy research suite on caller-supplied data only.

    This endpoint is stateless: no PostgreSQL access, no order execution, and
    no parameter search on out-of-sample data.
    """
    if not isinstance(payload, dict):
        raise ValueError("Request body must be an object")
    candles = _normalize_market(payload.get("candles_by_symbol"))
    strategies = _validate_strategies(payload.get("strategies"))
    initial_equity = _number(payload.get("initial_equity", 10000), "initial_equity", minimum=1e-9)
    spread = _number(payload.get("spread", 0), "spread", minimum=0)
    slippage = _number(payload.get("slippage", 0), "slippage", minimum=0)
    commission = _number(payload.get("commission_pct", 0.04), "commission_pct", minimum=0, maximum=5)
    max_open = int(payload.get("max_open_trades", 3))
    if not 1 <= max_open <= 100:
        raise ValueError("max_open_trades must be between 1 and 100")
    folds = int(payload.get("folds", 3))
    simulations = int(payload.get("monte_carlo_simulations", 200))
    seed = int(payload.get("random_seed", 42))
    stress_multiplier = _number(payload.get("stress_cost_multiplier", 2), "stress_cost_multiplier", minimum=1, maximum=10)
    if not 2 <= folds <= 10:
        raise ValueError("folds must be between 2 and 10")
    if not 100 <= simulations <= 1000:
        raise ValueError("monte_carlo_simulations must be between 100 and 1000")
    if not 0 <= seed <= 2**32 - 1:
        raise ValueError("random_seed must be an unsigned 32-bit integer")

    strategy_reports = []
    for strategy in strategies:
        validation = validate_strategy_walk_forward(
            candles, strategy["signals"],
            initial_equity=initial_equity, spread=spread, slippage=slippage,
            commission_pct=commission, max_open_trades=max_open,
            folds=folds, monte_carlo_simulations=simulations,
            random_seed=seed, stress_cost_multiplier=stress_multiplier,
        )
        regime_report = _strategy_regime_breakdown(
            candles, strategy["signals"], initial_equity=initial_equity,
            spread=spread, slippage=slippage, commission_pct=commission,
            max_open_trades=max_open,
        )
        strategy_reports.append({
            "strategy_id": strategy["strategy_id"],
            "name": strategy["name"],
            "validation": validation,
            "regime_performance": regime_report,
        })

    def rank_key(item: dict[str, Any]) -> tuple[float, float, float, str]:
        metrics = item["validation"].get("aggregate_oos", {})
        expectancy = metrics.get("expectancy_per_trade")
        pf = metrics.get("profit_factor")
        dd = metrics.get("trade_sequence_max_drawdown_pct")
        expectancy_value = float(expectancy) if isinstance(expectancy, (int, float)) else -1e12
        pf_value = 999.0 if pf == "infinite" else float(pf) if isinstance(pf, (int, float)) else 0.0
        dd_value = float(dd) if isinstance(dd, (int, float)) else 1000.0
        return (expectancy_value, pf_value, -dd_value, item["strategy_id"])

    ranked = sorted(strategy_reports, key=rank_key, reverse=True)
    comparison = []
    for position, item in enumerate(ranked, 1):
        metrics = item["validation"].get("aggregate_oos", {})
        trade_count = int(metrics.get("trade_count", 0))
        consistency = float(metrics.get("positive_fold_ratio_pct", 0) or 0)
        score = min(100.0, max(0.0,
            40.0 * consistency / 100.0
            + min(30.0, max(0.0, float(metrics.get("win_rate_pct") or 0) * 0.3))
            + min(30.0, max(0.0, float(metrics.get("profit_factor") or 0) * 10 if isinstance(metrics.get("profit_factor"), (int, float)) else 0))
        ))
        if trade_count < 30:
            score = min(score, 35.0)
        elif trade_count < 100:
            score = min(score, 60.0)
        comparison.append({
            "rank": position, "strategy_id": item["strategy_id"],
            "trade_count": trade_count, "expectancy_per_trade": metrics.get("expectancy_per_trade"),
            "profit_factor": metrics.get("profit_factor"),
            "win_rate_pct": metrics.get("win_rate_pct"),
            "positive_fold_ratio_pct": metrics.get("positive_fold_ratio_pct"),
            "robustness_score_heuristic": round(score, 2),
            "sample_size_warning": trade_count < 100,
        })

    risk_candidates = payload.get("risk_candidates", [])
    if not isinstance(risk_candidates, list) or len(risk_candidates) > 50:
        raise ValueError("risk_candidates must be a list of at most 50 items")
    risk_levels = payload.get("risk_levels_pct", [0.25, 0.5, 0.75, 1.0])
    if not isinstance(risk_levels, list) or not 1 <= len(risk_levels) <= 8:
        raise ValueError("risk_levels_pct must contain 1..8 values")
    risk_levels = [_number(v, "risk level", minimum=0.01, maximum=5) for v in risk_levels]
    risk_sensitivity = _risk_sensitivity(
        risk_candidates, equity=initial_equity, risk_levels=risk_levels,
        max_notional_pct=_number(payload.get("max_notional_pct", 100), "max_notional_pct", minimum=0.01, maximum=1000),
    )

    allocation_candidates = payload.get("allocation_candidates", [])
    if not isinstance(allocation_candidates, list) or len(allocation_candidates) > 50:
        raise ValueError("allocation_candidates must be a list of at most 50 items")
    allocation = {"status": "not_run", "reason": "No allocation_candidates supplied"}
    if allocation_candidates:
        allocation = allocate_capital(
            equity=initial_equity, candidates=allocation_candidates,
            current_open_risk_cash=_number(payload.get("current_open_risk_cash", 0), "current_open_risk_cash", minimum=0),
            max_portfolio_risk_pct=_number(payload.get("max_portfolio_risk_pct", 3), "max_portfolio_risk_pct", minimum=0, maximum=100),
            max_trade_risk_pct=_number(payload.get("max_trade_risk_pct", 1), "max_trade_risk_pct", minimum=0.000001, maximum=100),
            max_open_trades=max_open,
            current_open_positions=int(payload.get("current_open_positions", 0)),
            requested_budget_pct=payload.get("requested_budget_pct"),
        )

    prices_by_symbol = payload.get("prices_by_symbol")
    correlation = {"status": "not_run", "reason": "No prices_by_symbol supplied"}
    if prices_by_symbol is not None:
        correlation = {"status": "completed", **calculate_correlation_matrix(prices_by_symbol)}

    forward_trades = payload.get("forward_trades", [])
    if not isinstance(forward_trades, list):
        raise ValueError("forward_trades must be a list")
    forward = _forward_analytics(forward_trades)

    latest_regimes = _latest_regimes(candles)
    benchmark = _benchmark(candles, strategy_reports, initial_equity)

    audits = []
    for item in strategy_reports:
        validation = item["validation"]
        metrics = validation.get("aggregate_oos", {})
        trade_count = int(metrics.get("trade_count", 0))
        completed_folds = int(metrics.get("completed_test_folds", 0))
        audits.append({
            "strategy_id": item["strategy_id"],
            "status": "insufficient_evidence" if trade_count < 30 or completed_folds < 2 else "review_required",
            "checks": {
                "walk_forward_completed": completed_folds >= 2,
                "minimum_30_oos_trades": trade_count >= 30,
                "minimum_100_oos_trades_preferred": trade_count >= 100,
                "monte_carlo_completed": validation.get("monte_carlo", {}).get("status") == "completed",
                "no_live_execution": validation.get("execution_allowed") is False,
            },
            "conclusion": "Research diagnostics only; no strategy is automatically approved for live trading.",
        })

    return {
        "status": "completed",
        "phase": "12",
        "suite": "strategy_validation_and_trading_intelligence",
        "strategy_comparison": comparison,
        "strategy_reports": strategy_reports,
        "market_regime_analysis": latest_regimes,
        "risk_sensitivity": risk_sensitivity,
        "portfolio_allocation": allocation,
        "correlation_analysis": correlation,
        "forward_testing_analytics": forward,
        "performance_benchmarking": benchmark,
        "final_strategy_audit": {
            "status": "completed",
            "strategy_audits": audits,
            "live_trading_approved": False,
            "execution_allowed": False,
        },
        "methodology": {
            "walk_forward": "Existing chronological OOS validation with independently reset folds.",
            "regime_attribution": "Signal-entry regime buckets are independently replayed using causal closed-candle context.",
            "risk_optimization": "Sensitivity scenarios only; no automatic parameter changes.",
            "portfolio_allocation": "Existing quality-weighted risk-budget allocator; output is advisory only.",
            "benchmarking": "Buy-and-hold price returns are context only; pooled independent-fold strategy PnL is not a compounded equity curve.",
        },
        "limitations": [
            "All inputs are caller-supplied historical or exported data; this service does not query PostgreSQL or Binance.",
            "Signals are supplied by the caller and are not regenerated or optimized inside each OOS fold.",
            "The heuristic robustness score is a ranking aid, not a probability or profitability guarantee.",
            "No strategy is automatically selected, modified, or approved for live execution.",
        ],
        "execution_allowed": False,
    }
