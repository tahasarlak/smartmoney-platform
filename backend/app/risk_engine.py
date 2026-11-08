"""Portfolio-level risk analytics and allocation helpers.

Pure calculations only: this module never submits, modifies, or cancels orders.
Correlation is calculated from caller-supplied aligned price observations; it is
not inferred from symbol names or fabricated when data is insufficient.
"""
from __future__ import annotations

import math
from typing import Any


def _finite_positive(value: Any, name: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be a finite positive number") from None
    if not math.isfinite(number) or number <= 0:
        raise ValueError(f"{name} must be a finite positive number")
    return number


def calculate_risk_position_size(
    *, equity: float, risk_pct: float, entry: float, stop: float,
    max_notional_pct: float = 100.0,
) -> dict[str, Any]:
    equity = _finite_positive(equity, "equity")
    entry = _finite_positive(entry, "entry")
    stop = _finite_positive(stop, "stop")
    risk_pct = float(risk_pct)
    max_notional_pct = float(max_notional_pct)
    if not math.isfinite(risk_pct) or not 0 < risk_pct <= 100:
        raise ValueError("risk_pct must be greater than 0 and at most 100")
    if not math.isfinite(max_notional_pct) or not 0 < max_notional_pct <= 1000:
        raise ValueError("max_notional_pct must be greater than 0 and at most 1000")
    distance = abs(entry - stop)
    if distance <= 0:
        raise ValueError("entry and stop must differ")
    risk_cash = equity * risk_pct / 100.0
    raw_quantity = risk_cash / distance
    max_quantity = equity * max_notional_pct / 100.0 / entry
    quantity = min(raw_quantity, max_quantity)
    actual_risk = quantity * distance
    return {
        "quantity": round(quantity, 10),
        "risk_cash": round(actual_risk, 8),
        "risk_pct": round(actual_risk / equity * 100.0, 6),
        "notional": round(quantity * entry, 8),
        "notional_pct": round(quantity * entry / equity * 100.0, 6),
        "capped_by_notional": quantity + 1e-12 < raw_quantity,
        "execution_allowed": False,
    }


def _returns(prices: list[float], symbol: str) -> list[float]:
    if len(prices) < 2:
        raise ValueError(f"{symbol} needs at least two prices")
    clean = [_finite_positive(x, f"{symbol} price") for x in prices]
    return [(clean[i] / clean[i - 1]) - 1.0 for i in range(1, len(clean))]


def _pearson(xs: list[float], ys: list[float]) -> float | None:
    n = min(len(xs), len(ys))
    if n < 2:
        return None
    xs, ys = xs[-n:], ys[-n:]
    mx, my = sum(xs) / n, sum(ys) / n
    dx, dy = [x - mx for x in xs], [y - my for y in ys]
    vx, vy = sum(x * x for x in dx), sum(y * y for y in dy)
    if vx <= 1e-24 or vy <= 1e-24:
        return None
    value = sum(a * b for a, b in zip(dx, dy)) / math.sqrt(vx * vy)
    return max(-1.0, min(1.0, value))


def calculate_correlation_matrix(
    prices_by_symbol: dict[str, list[float]], min_observations: int = 20,
) -> dict[str, Any]:
    if not isinstance(prices_by_symbol, dict) or not 2 <= len(prices_by_symbol) <= 50:
        raise ValueError("Provide price series for 2..50 symbols")
    if not 3 <= int(min_observations) <= 5000:
        raise ValueError("min_observations must be between 3 and 5000")
    normalized: dict[str, list[float]] = {}
    for raw_symbol, prices in prices_by_symbol.items():
        symbol = str(raw_symbol).strip().upper()
        if not symbol or len(symbol) > 40 or symbol in normalized:
            raise ValueError("Symbols must be unique, non-empty and at most 40 characters")
        if not isinstance(prices, list):
            raise ValueError(f"Prices for {symbol} must be a list")
        normalized[symbol] = _returns(prices, symbol)
    lengths = {len(v) for v in normalized.values()}
    if len(lengths) != 1:
        raise ValueError("All price series must be aligned and have equal length")
    observations = next(iter(lengths))
    if observations < min_observations:
        raise ValueError(f"At least {min_observations + 1} prices per symbol are required")
    symbols = sorted(normalized)
    matrix: dict[str, dict[str, float | None]] = {}
    for a in symbols:
        matrix[a] = {}
        for b in symbols:
            matrix[a][b] = 1.0 if a == b else (
                round(_pearson(normalized[a], normalized[b]), 6)
                if _pearson(normalized[a], normalized[b]) is not None else None
            )
    pairs = []
    for i, a in enumerate(symbols):
        for b in symbols[i + 1:]:
            corr = matrix[a][b]
            pairs.append({"symbol_a": a, "symbol_b": b, "correlation": corr,
                          "relationship": "unavailable" if corr is None else
                          "strong_positive" if corr >= 0.75 else
                          "moderate_positive" if corr >= 0.4 else
                          "strong_negative" if corr <= -0.75 else
                          "moderate_negative" if corr <= -0.4 else "weak"})
    return {"symbols": symbols, "return_observations": observations,
            "method": "pearson_correlation_of_simple_returns",
            "matrix": matrix, "pairs": pairs,
            "note": "Historical correlation is descriptive, not a guarantee of future co-movement."}


def assess_portfolio_risk(
    *, equity: float, positions: list[dict[str, Any]],
    max_portfolio_risk_pct: float, max_trade_risk_pct: float,
    max_open_trades: int,
) -> dict[str, Any]:
    equity = _finite_positive(equity, "equity")
    if not 0 <= float(max_portfolio_risk_pct) <= 100:
        raise ValueError("max_portfolio_risk_pct must be between 0 and 100")
    if not 0 <= float(max_trade_risk_pct) <= 100:
        raise ValueError("max_trade_risk_pct must be between 0 and 100")
    if not 1 <= int(max_open_trades) <= 100:
        raise ValueError("max_open_trades must be between 1 and 100")
    symbol_risk: dict[str, float] = {}
    direction_risk: dict[str, float] = {}
    notional = 0.0
    total_risk = 0.0
    normalized = []
    blockers: list[str] = []
    warnings: list[str] = []
    for item in positions:
        symbol = str(item.get("symbol", "")).strip().upper()
        direction = str(item.get("direction", item.get("side", ""))).strip().lower()
        if direction in ("bullish",): direction = "long"
        if direction in ("bearish",): direction = "short"
        if not symbol or direction not in ("long", "short"):
            raise ValueError("Each position needs a symbol and long/short direction")
        qty = _finite_positive(item.get("quantity"), "position quantity")
        entry = _finite_positive(item.get("entry_price", item.get("entry")), "position entry")
        stop = _finite_positive(item.get("stop_loss", item.get("stop")), "position stop")
        risk = float(item.get("risk_cash", abs(entry - stop) * qty))
        if not math.isfinite(risk) or risk < 0:
            raise ValueError("position risk_cash must be finite and non-negative")
        exposure = qty * entry
        total_risk += risk
        notional += exposure
        symbol_risk[symbol] = symbol_risk.get(symbol, 0.0) + risk
        direction_risk[direction] = direction_risk.get(direction, 0.0) + risk
        position_risk_pct = risk / equity * 100
        if position_risk_pct > max_trade_risk_pct + 1e-9:
            blockers.append(f"per_trade_risk_limit_exceeded:{symbol}")
        normalized.append({"symbol": symbol, "direction": direction,
                           "risk_cash": round(risk, 8), "risk_pct": round(position_risk_pct, 6),
                           "notional": round(exposure, 8)})
    risk_pct = total_risk / equity * 100
    notional_pct = notional / equity * 100
    if len(positions) > max_open_trades:
        blockers.append("open_position_count_exceeds_configured_limit")
    if risk_pct > max_portfolio_risk_pct + 1e-9:
        blockers.append("aggregate_open_risk_exceeds_configured_limit")
    elif max_portfolio_risk_pct > 0 and risk_pct >= max_portfolio_risk_pct * 0.8:
        warnings.append("aggregate_open_risk_is_at_least_80_percent_of_limit")
    symbol_breakdown = {k: {"risk_cash": round(v, 8), "risk_pct": round(v / equity * 100, 6)}
                        for k, v in sorted(symbol_risk.items())}
    direction_breakdown = {k: {"risk_cash": round(v, 8), "risk_pct": round(v / equity * 100, 6)}
                           for k, v in sorted(direction_risk.items())}
    return {
        "equity": round(equity, 8), "position_count": len(positions),
        "total_open_risk_cash": round(total_risk, 8), "total_open_risk_pct": round(risk_pct, 6),
        "gross_notional": round(notional, 8), "gross_notional_pct_of_equity": round(notional_pct, 6),
        "remaining_risk_budget_cash": round(max(0.0, equity * max_portfolio_risk_pct / 100 - total_risk), 8),
        "remaining_position_slots": max(0, max_open_trades - len(positions)),
        "risk_limit_pct": float(max_portfolio_risk_pct),
        "per_trade_limit_pct": float(max_trade_risk_pct),
        "risk_by_symbol": symbol_breakdown, "risk_by_direction": direction_breakdown,
        "positions": normalized, "blockers": blockers, "warnings": warnings,
        "status": "blocked" if blockers else "warning" if warnings else "healthy",
        "execution_allowed": False,
    }


def allocate_capital(
    *, equity: float, candidates: list[dict[str, Any]], current_open_risk_cash: float,
    max_portfolio_risk_pct: float, max_trade_risk_pct: float,
    max_open_trades: int, current_open_positions: int,
    requested_budget_pct: float | None = None,
) -> dict[str, Any]:
    equity = _finite_positive(equity, "equity")
    if not candidates or len(candidates) > 50:
        raise ValueError("Provide 1..50 allocation candidates")
    if not math.isfinite(float(current_open_risk_cash)) or current_open_risk_cash < 0:
        raise ValueError("current_open_risk_cash must be non-negative")
    if not 0 <= max_portfolio_risk_pct <= 100 or not 0 < max_trade_risk_pct <= 100:
        raise ValueError("Invalid portfolio or per-trade risk limits")
    if not 1 <= max_open_trades <= 100 or current_open_positions < 0:
        raise ValueError("Invalid open-position limits")
    budget_pct = max_portfolio_risk_pct if requested_budget_pct is None else float(requested_budget_pct)
    if not math.isfinite(budget_pct) or not 0 < budget_pct <= max_portfolio_risk_pct:
        raise ValueError("requested_budget_pct must be positive and no greater than portfolio risk limit")
    free_slots = max(0, max_open_trades - current_open_positions)
    budget_cash = max(0.0, equity * budget_pct / 100.0 - current_open_risk_cash)
    accepted = []
    rejected = []
    seen = set()
    for c in candidates:
        symbol = str(c.get("symbol", "")).strip().upper()
        direction = str(c.get("direction", "")).strip().lower()
        entry = _finite_positive(c.get("entry"), "candidate entry")
        stop = _finite_positive(c.get("stop"), "candidate stop")
        score = float(c.get("quality_score", 0))
        if not symbol or len(symbol) > 40 or direction not in ("long", "short"):
            raise ValueError("Candidates require symbol and long/short direction")
        if not math.isfinite(score) or not 0 <= score <= 100:
            raise ValueError("quality_score must be between 0 and 100")
        if (direction == "long" and stop >= entry) or (direction == "short" and stop <= entry):
            raise ValueError(f"Stop is on the wrong side for {symbol}")
        key = (symbol, direction)
        if key in seen:
            raise ValueError("Duplicate symbol/direction candidates are not allowed")
        seen.add(key)
        if score <= 0:
            rejected.append({"symbol": symbol, "reason": "zero_quality_score"})
        else:
            accepted.append({"symbol": symbol, "direction": direction, "entry": entry,
                             "stop": stop, "quality_score": score,
                             "correlation_group": str(c.get("correlation_group") or symbol)[:64]})
    accepted = sorted(accepted, key=lambda x: (-x["quality_score"], x["symbol"], x["direction"]))[:free_slots]
    if not accepted or budget_cash <= 0:
        return {"equity": round(equity, 8), "budget_cash": round(budget_cash, 8),
                "allocations": [], "rejected": rejected + [{"reason": "no_available_risk_budget_or_position_slots"}],
                "execution_allowed": False}
    weights_total = sum(x["quality_score"] for x in accepted)
    allocations = []
    for c in accepted:
        requested = budget_cash * c["quality_score"] / weights_total
        cap = equity * max_trade_risk_pct / 100.0
        risk_cash = min(requested, cap)
        quantity = risk_cash / abs(c["entry"] - c["stop"])
        allocations.append({
            "symbol": c["symbol"], "direction": c["direction"],
            "quality_score": c["quality_score"], "entry": c["entry"], "stop": c["stop"],
            "risk_cash": round(risk_cash, 8), "risk_pct": round(risk_cash / equity * 100, 6),
            "quantity": round(quantity, 10), "notional": round(quantity * c["entry"], 8),
            "correlation_group": c["correlation_group"],
        })
    allocated = sum(x["risk_cash"] for x in allocations)
    return {"equity": round(equity, 8), "budget_cash": round(budget_cash, 8),
            "allocated_risk_cash": round(allocated, 8),
            "unallocated_risk_cash": round(max(0.0, budget_cash - allocated), 8),
            "allocations": allocations, "rejected": rejected,
            "allocation_method": "quality_score_weighted_capped_by_per_trade_limit",
            "execution_allowed": False,
            "note": "Correlation groups are labels only in this phase; measured correlation is returned by the separate correlation endpoint."}


def allocate_capital_with_correlation(
    *, equity: float, candidates: list[dict[str, Any]],
    prices_by_symbol: dict[str, list[float]], current_open_risk_cash: float,
    max_portfolio_risk_pct: float, max_trade_risk_pct: float,
    max_open_trades: int, current_open_positions: int,
    requested_budget_pct: float | None = None,
    correlation_penalty_strength: float = 1.0,
    min_observations: int = 20,
) -> dict[str, Any]:
    """Heuristically reduce risk weights for candidates duplicating same-direction exposure.

    Correlation is estimated from aligned, caller-supplied price histories. Effective
    correlation is multiplied by trade-direction signs: positive values indicate
    historically similar PnL direction. This is a conservative weighting heuristic,
    not covariance optimization or a guarantee of future diversification.
    """
    if not math.isfinite(float(correlation_penalty_strength)) or not 0 <= correlation_penalty_strength <= 5:
        raise ValueError("correlation_penalty_strength must be between 0 and 5")
    if not isinstance(candidates, list) or not candidates:
        raise ValueError("Provide at least one candidate")
    symbols = [str(c.get("symbol", "")).strip().upper() for c in candidates]
    if len(set(symbols)) != len(symbols):
        raise ValueError("Correlation-aware allocation requires unique candidate symbols")
    if not isinstance(prices_by_symbol, dict):
        raise ValueError("prices_by_symbol must be a mapping")
    missing = sorted(set(symbols) - {str(k).strip().upper() for k in prices_by_symbol})
    if missing:
        raise ValueError(f"Missing price history for candidate symbols: {', '.join(missing)}")

    # Keep only candidate series and normalize symbol keys; the matrix function
    # enforces positive finite prices, aligned lengths and sufficient observations.
    normalized_prices = {
        str(k).strip().upper(): v
        for k, v in prices_by_symbol.items()
        if str(k).strip().upper() in set(symbols)
    }
    correlation = calculate_correlation_matrix(normalized_prices, min_observations)
    matrix = correlation["matrix"]

    normalized_candidates = []
    for raw in candidates:
        item = dict(raw)
        symbol = str(item.get("symbol", "")).strip().upper()
        direction = str(item.get("direction", "")).strip().lower()
        if direction not in ("long", "short"):
            raise ValueError(f"Invalid direction for {symbol}")
        normalized_candidates.append({**item, "symbol": symbol, "direction": direction})

    direction_sign = {"long": 1.0, "short": -1.0}
    diagnostics = {}
    adjusted_candidates = []
    for candidate in normalized_candidates:
        symbol = candidate["symbol"]
        effective_values = []
        for other in normalized_candidates:
            if other["symbol"] == symbol:
                continue
            raw_corr = matrix[symbol][other["symbol"]]
            if raw_corr is None:
                continue
            effective = raw_corr * direction_sign[candidate["direction"]] * direction_sign[other["direction"]]
            effective_values.append(effective)
        positive_crowding = [max(0.0, value) for value in effective_values]
        avg_crowding = (
            sum(positive_crowding) / len(positive_crowding)
            if positive_crowding else 0.0
        )
        penalty = 1.0 + correlation_penalty_strength * avg_crowding
        original_score = float(candidate.get("quality_score", 0))
        adjusted_score = original_score / penalty
        diagnostics[symbol] = {
            "average_effective_correlation": round(
                sum(effective_values) / len(effective_values), 6
            ) if effective_values else None,
            "positive_correlation_crowding": round(avg_crowding, 6),
            "correlation_penalty_factor": round(penalty, 6),
            "original_quality_score": original_score,
            "adjusted_allocation_score": round(adjusted_score, 6),
            "comparable_pairs": len(effective_values),
        }
        adjusted_candidates.append({**candidate, "quality_score": adjusted_score})

    base = allocate_capital(
        equity=equity,
        candidates=adjusted_candidates,
        current_open_risk_cash=current_open_risk_cash,
        max_portfolio_risk_pct=max_portfolio_risk_pct,
        max_trade_risk_pct=max_trade_risk_pct,
        max_open_trades=max_open_trades,
        current_open_positions=current_open_positions,
        requested_budget_pct=requested_budget_pct,
    )
    for allocation in base.get("allocations", []):
        symbol = allocation["symbol"]
        info = diagnostics[symbol]
        allocation["quality_score"] = info["original_quality_score"]
        allocation["adjusted_allocation_score"] = info["adjusted_allocation_score"]
        allocation["average_effective_correlation"] = info["average_effective_correlation"]
        allocation["positive_correlation_crowding"] = info["positive_correlation_crowding"]
        allocation["correlation_penalty_factor"] = info["correlation_penalty_factor"]
    base.update({
        "correlation": {
            "method": correlation["method"],
            "return_observations": correlation["return_observations"],
            "matrix": matrix,
            "pairs": correlation["pairs"],
            "penalty_strength": correlation_penalty_strength,
            "direction_adjusted": True,
        },
        "candidate_diagnostics": diagnostics,
        "allocation_method": "quality_score_weighted_with_direction_adjusted_correlation_penalty",
        "execution_allowed": False,
        "note": (
            "Correlation reduces allocation weights for candidates with historically similar "
            "direction-adjusted returns. This is a heuristic, not covariance optimization; "
            "historical correlations can change. No orders are created."
        ),
    })
    return base
