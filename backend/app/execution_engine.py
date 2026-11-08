"""Deterministic paper-execution state machine. No broker or live-order adapter exists here."""
from __future__ import annotations

import math
from typing import Any

ACTIVE_STATUSES = {"open", "partially_closed"}
TERMINAL_STATUSES = {"closed", "cancelled"}
DEFAULT_TARGET_FRACTIONS = (0.50, 0.30, 0.20)


def _positive(value: Any, name: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be finite and positive") from None
    if not math.isfinite(number) or number <= 0:
        raise ValueError(f"{name} must be finite and positive")
    return number


def validate_execution_plan(
    *, side: str, quantity: float, planned_entry: float, stop_loss: float,
    tp1: float, tp2: float, tp3: float, commission_pct: float = 0.04,
    slippage_bps: float = 2.0, target_fractions: tuple[float, float, float] = DEFAULT_TARGET_FRACTIONS,
    trailing_stop_pct: float | None = None,
) -> dict[str, Any]:
    side = str(side).strip().lower()
    if side not in ("long", "short"):
        raise ValueError("side must be long or short")
    values = {name: _positive(value, name) for name, value in {
        "quantity": quantity, "planned_entry": planned_entry, "stop_loss": stop_loss,
        "tp1": tp1, "tp2": tp2, "tp3": tp3,
    }.items()}
    entry, stop, a, b, c = (values[k] for k in ("planned_entry", "stop_loss", "tp1", "tp2", "tp3"))
    if side == "long" and not stop < entry < a < b < c:
        raise ValueError("Long plan requires stop_loss < planned_entry < tp1 < tp2 < tp3")
    if side == "short" and not c < b < a < entry < stop:
        raise ValueError("Short plan requires tp3 < tp2 < tp1 < planned_entry < stop_loss")
    commission_pct, slippage_bps = float(commission_pct), float(slippage_bps)
    if not math.isfinite(commission_pct) or not 0 <= commission_pct <= 5:
        raise ValueError("commission_pct must be between 0 and 5")
    if not math.isfinite(slippage_bps) or not 0 <= slippage_bps <= 1000:
        raise ValueError("slippage_bps must be between 0 and 1000")
    if len(target_fractions) != 3:
        raise ValueError("Exactly three target fractions are required")
    fractions = tuple(float(x) for x in target_fractions)
    if any(not math.isfinite(x) or x <= 0 or x > 1 for x in fractions) or not math.isclose(sum(fractions), 1.0, abs_tol=1e-9):
        raise ValueError("Target fractions must be positive and sum to 1")
    if trailing_stop_pct is not None:
        trailing_stop_pct = float(trailing_stop_pct)
        if not math.isfinite(trailing_stop_pct) or not 0 < trailing_stop_pct <= 20:
            raise ValueError("trailing_stop_pct must be greater than 0 and at most 20")
    return {**values, "side": side, "commission_pct": commission_pct,
            "slippage_bps": slippage_bps, "tp1_fraction": fractions[0],
            "tp2_fraction": fractions[1], "tp3_fraction": fractions[2],
            "trailing_stop_pct": trailing_stop_pct}


def entry_triggered(side: str, market_price: float, planned_entry: float) -> bool:
    return market_price <= planned_entry if side == "long" else market_price >= planned_entry


def adverse_fill(market_price: float, side: str, is_entry: bool, slippage_bps: float) -> float:
    market_price = _positive(market_price, "market_price")
    if side not in ("long", "short"):
        raise ValueError("side must be long or short")
    slip = float(slippage_bps) / 10_000.0
    if not math.isfinite(slip) or not 0 <= slip <= 0.1:
        raise ValueError("slippage_bps must be between 0 and 1000")
    buy = (side == "long" and is_entry) or (side == "short" and not is_entry)
    return market_price * (1.0 + slip if buy else 1.0 - slip)


def _pnl(side: str, entry: float, exit_price: float, quantity: float) -> float:
    return (exit_price - entry) * quantity if side == "long" else (entry - exit_price) * quantity


def process_trade_tick(
    state: dict[str, Any], *, market_price: float, event_time_ms: int,
    event_id: str, force_close: bool = False,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Apply one unique, strictly chronological price observation to a trade."""
    price = _positive(market_price, "market_price")
    if isinstance(event_time_ms, bool) or int(event_time_ms) <= 0:
        raise ValueError("event_time_ms must be a positive integer")
    if not event_id or len(str(event_id)) > 80:
        raise ValueError("event_id must contain 1..80 characters")
    current = dict(state)
    if current.get("status") in TERMINAL_STATUSES:
        raise ValueError("Trade is already terminal")
    if int(event_time_ms) <= int(current.get("last_event_time_ms", 0)):
        raise ValueError("Market events must be strictly chronological")

    side = current["side"]
    quantity = float(current["quantity"])
    remaining = float(current["remaining_quantity"])
    commission = float(current["commission_pct"]) / 100.0
    slippage = float(current["slippage_bps"])
    events: list[dict[str, Any]] = []
    current["last_price"] = price
    current["last_event_time_ms"] = int(event_time_ms)

    def emit(kind: str, fill: float | None = None, qty: float = 0.0,
             pnl: float = 0.0, fee: float = 0.0, details: dict | None = None):
        events.append({"event_type": kind, "market_price": price, "fill_price": fill,
                       "quantity": qty, "pnl": pnl, "fee": fee, "details": details or {}})

    if current["status"] == "pending_entry":
        if force_close:
            raise ValueError("A pending entry cannot be closed before it fills; cancel it instead")
        if not entry_triggered(side, price, float(current["planned_entry"])):
            emit("PRICE_OBSERVED")
            return current, events
        fill = adverse_fill(price, side, True, slippage)
        fee = fill * quantity * commission
        current.update({"status": "open", "avg_entry_price": fill,
                        "entry_filled_at_ms": int(event_time_ms),
                        "fees_paid": float(current.get("fees_paid", 0.0)) + fee,
                        "high_water": fill, "low_water": fill})
        emit("ENTRY_FILLED", fill, quantity, 0.0, fee,
             {"planned_entry": current["planned_entry"], "slippage_bps": slippage})
        return current, events

    if current["status"] not in ACTIVE_STATUSES:
        raise ValueError("Trade cannot accept price updates in its current state")

    stop = float(current["stop_loss"])
    stop_hit = price <= stop if side == "long" else price >= stop
    if force_close or stop_hit:
        fill = adverse_fill(price, side, False, slippage)
        gross = _pnl(side, float(current["avg_entry_price"]), fill, remaining)
        fee = fill * remaining * commission
        current.update({"remaining_quantity": 0.0,
                        "realized_pnl": float(current.get("realized_pnl", 0.0)) + gross,
                        "fees_paid": float(current.get("fees_paid", 0.0)) + fee,
                        "status": "closed", "closed_at_ms": int(event_time_ms)})
        emit("MANUAL_CLOSE_FILLED" if force_close else "STOP_FILLED", fill, remaining, gross, fee)
        return current, events

    for target_no in (1, 2, 3):
        key = f"tp{target_no}_hit"
        if current.get(key):
            continue
        target = float(current[f"tp{target_no}"])
        reached = price >= target if side == "long" else price <= target
        if not reached:
            continue
        fraction = float(current[f"tp{target_no}_fraction"])
        exit_qty = remaining if target_no == 3 else min(remaining, quantity * fraction)
        if exit_qty <= 1e-12:
            current[key] = True
            continue
        fill = adverse_fill(price, side, False, slippage)
        gross = _pnl(side, float(current["avg_entry_price"]), fill, exit_qty)
        fee = fill * exit_qty * commission
        remaining = max(0.0, remaining - exit_qty)
        current[key] = True
        current["remaining_quantity"] = remaining
        current["realized_pnl"] = float(current.get("realized_pnl", 0.0)) + gross
        current["fees_paid"] = float(current.get("fees_paid", 0.0)) + fee
        current["status"] = "closed" if remaining <= max(1e-12, quantity * 1e-10) else "partially_closed"
        if current["status"] == "closed":
            current["remaining_quantity"] = 0.0
            current["closed_at_ms"] = int(event_time_ms)
        emit(f"TP{target_no}_FILLED", fill, exit_qty, gross, fee,
             {"target_price": target, "remaining_quantity": current["remaining_quantity"]})
        if target_no == 1 and current.get("move_stop_to_breakeven_after_tp1"):
            entry = float(current["avg_entry_price"])
            current["stop_loss"] = max(float(current["stop_loss"]), entry) if side == "long" else min(float(current["stop_loss"]), entry)
            emit("STOP_MOVED_TO_BREAKEVEN", details={"stop_loss": current["stop_loss"]})
        if current["status"] == "closed":
            break

    if current["status"] in ACTIVE_STATUSES and current.get("trailing_stop_pct") is not None:
        trail = float(current["trailing_stop_pct"]) / 100.0
        if side == "long":
            high = max(float(current.get("high_water") or price), price)
            current["high_water"] = high
            candidate = high * (1.0 - trail)
            current["stop_loss"] = max(float(current["stop_loss"]), candidate)
        else:
            low = min(float(current.get("low_water") or price), price)
            current["low_water"] = low
            candidate = low * (1.0 + trail)
            current["stop_loss"] = min(float(current["stop_loss"]), candidate)
        emit("TRAILING_STOP_UPDATED", details={"stop_loss": current["stop_loss"]})

    if not events:
        emit("PRICE_OBSERVED")
    return current, events


def cancel_pending_trade(state: dict[str, Any]) -> dict[str, Any]:
    current = dict(state)
    if current.get("status") != "pending_entry":
        raise ValueError("Only a pending-entry trade can be cancelled")
    current["status"] = "cancelled"
    current["remaining_quantity"] = 0.0
    return current
