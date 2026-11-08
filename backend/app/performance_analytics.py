"""Realized paper-execution performance analytics.

Metrics are derived only from persisted, closed paper execution trades.
No forecasts, live prices, or synthetic trade outcomes are generated.
"""
from __future__ import annotations

import math
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any


def _number(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def _timestamp(trade: dict[str, Any]) -> int:
    value = trade.get("closed_at_ms") or trade.get("last_event_time_ms") or 0
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _ratio(numerator: float, denominator: float) -> float | None:
    return numerator / denominator if denominator > 1e-15 else None


def _profit_factor(values: list[float]) -> float | None:
    gross_profit = sum(x for x in values if x > 0)
    gross_loss = -sum(x for x in values if x < 0)
    if gross_loss <= 1e-15:
        return None if gross_profit <= 1e-15 else None
    return gross_profit / gross_loss


def _moments(values: list[float]) -> tuple[float | None, float | None]:
    """Return non-annualized per-trade Sharpe and Sortino-like ratios."""
    if len(values) < 2:
        return None, None
    mean = sum(values) / len(values)
    variance = sum((x - mean) ** 2 for x in values) / (len(values) - 1)
    std = math.sqrt(max(0.0, variance))
    sharpe = mean / std if std > 1e-15 else None
    downside = [min(0.0, x) ** 2 for x in values]
    downside_deviation = math.sqrt(sum(downside) / len(values))
    sortino = mean / downside_deviation if downside_deviation > 1e-15 else None
    return sharpe, sortino


def build_portfolio_performance(
    *, initial_equity: float, trades: list[dict[str, Any]], requested_limit: int = 500
) -> dict[str, Any]:
    """Build portfolio KPIs and symbol/side cohorts from execution trade records."""
    initial_equity = _number(initial_equity, -1)
    if not math.isfinite(initial_equity) or initial_equity <= 0:
        raise ValueError("initial_equity must be finite and positive")
    if not isinstance(trades, list):
        raise ValueError("trades must be a list")

    # Net realized P&L to date includes partial exits on still-open trades.
    realized_to_date = sum(_number(t.get("net_realized_pnl"),
                                   _number(t.get("realized_pnl")) - _number(t.get("fees_paid")))
                           for t in trades)

    closed = []
    for trade in trades:
        if str(trade.get("status", "")).lower() != "closed":
            continue
        net = _number(trade.get("net_realized_pnl"),
                      _number(trade.get("realized_pnl")) - _number(trade.get("fees_paid")))
        risk = abs(_number(trade.get("planned_entry")) -
                   _number(trade.get("initial_stop_loss", trade.get("stop_loss")))) * _number(trade.get("quantity"))
        r_multiple = _ratio(net, risk)
        closed.append({
            "id": str(trade.get("id", "")),
            "symbol": str(trade.get("symbol", "UNKNOWN")).upper(),
            "side": str(trade.get("side", "unknown")).lower(),
            "net_pnl": net,
            "r_multiple": r_multiple,
            "time_ms": _timestamp(trade),
        })
    closed.sort(key=lambda item: (item["time_ms"], item["id"]))

    equity = initial_equity
    peak = initial_equity
    max_dd_cash = 0.0
    max_dd_pct = 0.0
    curve = [{"time_ms": None, "equity": round(equity, 8),
              "drawdown_cash": 0.0, "drawdown_pct": 0.0}]
    for item in closed:
        equity += item["net_pnl"]
        peak = max(peak, equity)
        dd_cash = max(0.0, peak - equity)
        dd_pct = dd_cash / peak * 100.0 if peak > 0 else 0.0
        max_dd_cash = max(max_dd_cash, dd_cash)
        max_dd_pct = max(max_dd_pct, dd_pct)
        curve.append({
            "time_ms": item["time_ms"] or None,
            "equity": round(equity, 8),
            "drawdown_cash": round(dd_cash, 8),
            "drawdown_pct": round(dd_pct, 6),
        })

    pnls = [x["net_pnl"] for x in closed]
    winners = [x for x in pnls if x > 0]
    losers = [x for x in pnls if x < 0]
    returns = [x["r_multiple"] for x in closed if x["r_multiple"] is not None]
    sharpe, sortino = _moments(returns)

    cohorts: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for item in closed:
        cohorts[(item["symbol"], item["side"])].append(item)
    ranking = []
    for (symbol, side), items in cohorts.items():
        values = [x["net_pnl"] for x in items]
        rs = [x["r_multiple"] for x in items if x["r_multiple"] is not None]
        pf = _profit_factor(values)
        ranking.append({
            "group": f"{symbol} · {side.upper()}",
            "symbol": symbol,
            "side": side,
            "closed_trades": len(items),
            "net_pnl": round(sum(values), 8),
            "win_rate_pct": round(sum(1 for x in values if x > 0) / len(values) * 100, 4),
            "profit_factor": round(pf, 6) if pf is not None else None,
            "expectancy_cash": round(sum(values) / len(values), 8),
            "average_r": round(sum(rs) / len(rs), 6) if rs else None,
        })
    ranking.sort(key=lambda x: (x["net_pnl"], x["expectancy_cash"]), reverse=True)

    count = len(closed)
    return {
        "status": "ok",
        "mode": "paper",
        "initial_equity": round(initial_equity, 8),
        "cash_equity_to_date": round(initial_equity + realized_to_date, 8),
        "realized_net_pnl_to_date": round(realized_to_date, 8),
        "closed_trade_count": count,
        "win_rate_pct": round(len(winners) / count * 100, 4) if count else None,
        "profit_factor": round(_profit_factor(pnls), 6) if _profit_factor(pnls) is not None else None,
        "expectancy_cash": round(sum(pnls) / count, 8) if count else None,
        "average_win_cash": round(sum(winners) / len(winners), 8) if winners else None,
        "average_loss_cash": round(sum(losers) / len(losers), 8) if losers else None,
        "max_drawdown_cash": round(max_dd_cash, 8),
        "max_drawdown_pct": round(max_dd_pct, 6),
        "sharpe_per_trade": round(sharpe, 6) if sharpe is not None else None,
        "sortino_per_trade": round(sortino, 6) if sortino is not None else None,
        "return_observations": len(returns),
        "equity_curve": curve,
        "cohort_ranking": ranking,
        "sample_quality": "insufficient" if count < 30 else "limited" if count < 100 else "larger_sample",
        "data_limit": requested_limit,
        "trades_returned": len(trades),
        "methodology": {
            "pnl": "realized_execution_pnl_less_fees",
            "performance_sample": "closed_paper_execution_trades_only",
            "return_unit": "R_multiple_per_trade",
            "sharpe_sortino": "non_annualized_per_trade_ratios",
            "drawdown": "closed_trade_realized_equity_curve",
            "ranking": "symbol_and_direction_cohorts_not_strategy_ids",
        },
        "limitations": [
            "Metrics cover persisted paper execution trades only; legacy paper orders and forward-test runs are not mixed in.",
            "Sharpe and Sortino are non-annualized per-trade ratios, not daily or annual investment statistics.",
            "Cohort ranking groups by symbol and direction because execution records do not contain a verified strategy identifier.",
            "A small trade sample is not statistically reliable; no profitability forecast or live-readiness certification is implied.",
            "Equity curve uses realized closed-trade outcomes and excludes mark-to-market valuation of open positions.",
        ],
        "execution_allowed": False,
    }
