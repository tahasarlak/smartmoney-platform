"""Fail-closed pre-trade limits for Binance Spot Testnet only."""
from __future__ import annotations

import math
import os
from decimal import Decimal, InvalidOperation
from typing import Iterable


def evaluate_testnet_order_limits(
    *,
    quantity: str,
    price: str,
    active_order_notionals: Iterable[Decimal | str | float],
    portfolio_equity: float,
    max_order_notional: float | None = None,
    max_open_orders: int | None = None,
    max_portfolio_exposure_pct: float | None = None,
) -> dict:
    """Check gross notional limits; this is not a stop-loss or liquidation-risk model."""
    try:
        qty, px = Decimal(str(quantity)), Decimal(str(price))
        equity = float(portfolio_equity)
    except (InvalidOperation, ValueError, TypeError, OverflowError) as exc:
        raise ValueError("Order and portfolio values must be numeric") from exc
    if not qty.is_finite() or not px.is_finite() or qty <= 0 or px <= 0:
        raise ValueError("Quantity and price must be finite and positive")
    if not math.isfinite(equity) or equity <= 0:
        raise ValueError("Portfolio equity must be finite and positive")

    def env_float(name: str, default: float) -> float:
        raw = os.getenv(name)
        try:
            value = default if raw is None else float(raw)
        except (TypeError, ValueError):
            raise ValueError(f"{name} must be numeric")
        if not math.isfinite(value) or value <= 0:
            raise ValueError(f"{name} must be finite and positive")
        return value

    def env_int(name: str, default: int) -> int:
        raw = os.getenv(name)
        try:
            value = default if raw is None else int(raw)
        except (TypeError, ValueError):
            raise ValueError(f"{name} must be an integer")
        if value < 1:
            raise ValueError(f"{name} must be positive")
        return value

    order_cap = float(max_order_notional) if max_order_notional is not None else env_float(
        "TRADF_TESTNET_MAX_ORDER_NOTIONAL_USDT", 50.0
    )
    open_cap = int(max_open_orders) if max_open_orders is not None else env_int(
        "TRADF_TESTNET_MAX_OPEN_ORDERS", 3
    )
    exposure_pct = float(max_portfolio_exposure_pct) if max_portfolio_exposure_pct is not None else env_float(
        "TRADF_TESTNET_MAX_PORTFOLIO_EXPOSURE_PCT", 10.0
    )
    if not math.isfinite(order_cap) or order_cap <= 0:
        raise ValueError("max_order_notional must be finite and positive")
    if open_cap < 1:
        raise ValueError("max_open_orders must be positive")
    if not math.isfinite(exposure_pct) or not 0 < exposure_pct <= 100:
        raise ValueError("max_portfolio_exposure_pct must be in (0, 100]")

    active = []
    for value in active_order_notionals:
        try:
            item = Decimal(str(value))
        except (InvalidOperation, ValueError, TypeError):
            raise ValueError("Existing order exposure contains invalid data")
        if not item.is_finite() or item < 0:
            raise ValueError("Existing order exposure must be finite and nonnegative")
        active.append(item)

    requested = qty * px
    current = sum(active, Decimal("0"))
    portfolio_cap = Decimal(str(equity)) * Decimal(str(exposure_pct)) / Decimal("100")
    reasons = []
    if requested > Decimal(str(order_cap)):
        reasons.append("single_order_notional_limit_exceeded")
    if len(active) >= open_cap:
        reasons.append("maximum_open_orders_reached")
    if current + requested > portfolio_cap:
        reasons.append("portfolio_gross_exposure_limit_exceeded")

    return {
        "allowed": not reasons,
        "requested_notional": float(requested),
        "current_open_order_notional": float(current),
        "projected_open_order_notional": float(current + requested),
        "single_order_notional_limit": order_cap,
        "max_open_orders": open_cap,
        "active_open_orders": len(active),
        "portfolio_exposure_limit_pct": exposure_pct,
        "portfolio_exposure_limit_notional": float(portfolio_cap),
        "reasons": reasons,
        "scope": "binance_spot_testnet_gross_order_notional_only",
        "execution_allowed": False,
    }


def worker_liveness(*, heartbeat_age_seconds: float, worker_status: str, stale_after_seconds: int = 30) -> dict:
    """Classify a heartbeat; never equates a healthy worker with trading permission."""
    try:
        age = float(heartbeat_age_seconds)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("heartbeat_age_seconds must be numeric") from exc
    if not math.isfinite(age) or age < 0 or stale_after_seconds < 1:
        raise ValueError("Invalid heartbeat age or stale threshold")
    running = str(worker_status).lower() == "running" and age <= stale_after_seconds
    return {
        "status": "healthy" if running else "stale",
        "worker_running": running,
        "heartbeat_age_seconds": round(age, 1),
        "stale_after_seconds": stale_after_seconds,
        "execution_allowed": False,
    }
