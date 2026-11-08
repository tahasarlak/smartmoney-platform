from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any


def _period(timestamp: int) -> tuple[str, str]:
    dt = datetime.fromtimestamp(timestamp, tz=timezone.utc)
    iso = dt.isocalendar()
    return dt.date().isoformat(), f"{iso.year}-W{iso.week:02d}"


def _validate_candles(symbol: str, candles: list[dict[str, Any]]) -> list[int]:
    if not isinstance(candles, list) or len(candles) < 3:
        raise ValueError(f"At least 3 candles are required for {symbol}")
    times: list[int] = []
    for i, candle in enumerate(candles):
        try:
            ts = int(candle["time"])
            o, h, lo, cl = (float(candle[k]) for k in ("open", "high", "low", "close"))
        except (KeyError, TypeError, ValueError, OverflowError) as exc:
            raise ValueError(f"Invalid candle for {symbol} at index {i}") from exc
        if not all(math.isfinite(v) and v > 0 for v in (o, h, lo, cl)):
            raise ValueError(f"Invalid OHLC values for {symbol} at index {i}")
        if not lo <= min(o, cl) <= max(o, cl) <= h:
            raise ValueError(f"OHLC invariant violated for {symbol} at index {i}")
        times.append(ts)
    if times != sorted(times) or len(times) != len(set(times)):
        raise ValueError(f"Candles for {symbol} must be strictly chronological without duplicates")
    return times


def run_multi_symbol_backtest(
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
) -> dict[str, Any]:
    """Chronological, shared-equity OHLC portfolio replay across symbols.

    A signal at symbol candle i enters at that symbol's candle i+1 open.
    All symbols are processed on one UTC timeline. Stop is assumed before
    target when both are touched in the same bar. Equity is close-marked.
    """
    if not isinstance(candles_by_symbol, dict) or not candles_by_symbol:
        raise ValueError("At least one symbol is required")
    if len(candles_by_symbol) > 30:
        raise ValueError("Maximum 30 symbols are supported")
    if not math.isfinite(initial_equity) or initial_equity <= 0:
        raise ValueError("initial_equity must be finite and positive")
    if any(not math.isfinite(v) or v < 0 for v in (spread, slippage, commission_pct)) or commission_pct > 5:
        raise ValueError("Trading costs must be finite and nonnegative; commission_pct cannot exceed 5")
    if not isinstance(max_open_trades, int) or not 1 <= max_open_trades <= 100:
        raise ValueError("max_open_trades must be between 1 and 100")
    for name, value in (("max_daily_loss_pct", max_daily_loss_pct),
                        ("max_weekly_loss_pct", max_weekly_loss_pct),
                        ("max_drawdown_pct", max_drawdown_pct)):
        if not math.isfinite(value) or not 0 <= value <= 100:
            raise ValueError(f"{name} must be between 0 and 100")

    normalized: dict[str, list[dict[str, Any]]] = {}
    times_by_symbol: dict[str, list[int]] = {}
    for raw_symbol, candles in candles_by_symbol.items():
        symbol = str(raw_symbol).strip().upper()
        if not symbol or len(symbol) > 30:
            raise ValueError("Invalid symbol")
        if symbol in normalized:
            raise ValueError(f"Duplicate symbol: {symbol}")
        normalized[symbol] = candles
        times_by_symbol[symbol] = _validate_candles(symbol, candles)

    # Each signal is scheduled at the timestamp of its next candle open.
    entries_by_time: dict[int, list[dict[str, Any]]] = {}
    for order, raw in enumerate(signals):
        try:
            symbol = str(raw["symbol"]).strip().upper()
            idx = int(raw["index"])
            direction = str(raw["direction"]).lower()
            stop, target = float(raw["stop_loss"]), float(raw["take_profit"])
            qty = float(raw.get("quantity", 1.0))
        except (KeyError, TypeError, ValueError, OverflowError) as exc:
            raise ValueError("Invalid multi-symbol signal fields") from exc
        if symbol not in normalized:
            raise ValueError(f"Signal references unknown symbol: {symbol}")
        if idx < 0 or idx >= len(normalized[symbol]) - 1:
            raise ValueError(f"Signal index for {symbol} must have a following candle")
        if direction not in ("bullish", "bearish"):
            raise ValueError("Signal direction must be bullish or bearish")
        if not all(math.isfinite(v) and v > 0 for v in (stop, target, qty)):
            raise ValueError("Stop, target and quantity must be finite and positive")
        entry_index = idx + 1
        entry_time = times_by_symbol[symbol][entry_index]
        raw_levels = raw.get("take_profits")
        partial_levels: list[dict[str, float]] = []
        if raw_levels is not None:
            if not isinstance(raw_levels, list) or not raw_levels:
                raise ValueError("take_profits must be a non-empty list")
            total_fraction = 0.0
            previous = None
            for level in raw_levels:
                try:
                    price, fraction = float(level["price"]), float(level["fraction"])
                except (KeyError, TypeError, ValueError, OverflowError) as exc:
                    raise ValueError("Each take-profit level needs price and fraction") from exc
                if not math.isfinite(price) or price <= 0 or not math.isfinite(fraction) or not 0 < fraction <= 1:
                    raise ValueError("Invalid take-profit price or fraction")
                if direction == "bullish":
                    valid = price > stop and (previous is None or price > previous)
                else:
                    valid = price < stop and (previous is None or price < previous)
                if not valid:
                    raise ValueError("Take-profit levels must be ordered beyond stop")
                partial_levels.append({"price": price, "fraction": fraction})
                total_fraction += fraction
                previous = price
            if not math.isclose(total_fraction, 1.0, abs_tol=1e-6):
                raise ValueError("Take-profit fractions must sum to 1.0")
        entries_by_time.setdefault(entry_time, []).append({
            "symbol": symbol, "signal_index": idx, "entry_index": entry_index,
            "direction": direction, "stop_loss": stop, "take_profit": target,
            "take_profits": partial_levels, "quantity": qty, "_order": order,
        })

    bars_by_time: dict[int, dict[str, tuple[int, dict[str, Any]]]] = {}
    for symbol, candles in normalized.items():
        for idx, (ts, candle) in enumerate(zip(times_by_symbol[symbol], candles)):
            bars_by_time.setdefault(ts, {})[symbol] = (idx, candle)
    timeline = sorted(bars_by_time)

    cash = float(initial_equity)
    peak = float(initial_equity)
    max_dd = 0.0
    active: list[dict[str, Any]] = []
    trades: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    equity_curve: list[dict[str, Any]] = []
    last_prices: dict[str, float] = {}
    day_key: str | None = None
    week_key: str | None = None
    day_start = float(initial_equity)
    week_start = float(initial_equity)
    blocks = {"capacity": 0, "daily": 0, "weekly": 0, "drawdown": 0}

    def mark_to_market(prices: dict[str, float]) -> float:
        unrealized = 0.0
        for pos in active:
            price = prices.get(pos["symbol"], pos["entry"])
            side = 1.0 if pos["direction"] == "bullish" else -1.0
            remaining_qty = pos.get("remaining_quantity", pos["quantity"])
            unrealized += (price - pos["entry"]) * remaining_qty * side
        return cash + unrealized

    def close_position(pos: dict[str, Any], candle: dict[str, Any], idx: int,
                       raw_exit: float, reason: str) -> None:
        """Close remaining size and record one aggregate trade after all exit legs."""
        nonlocal cash
        long_side = pos["direction"] == "bullish"
        qty = float(pos.get("remaining_quantity", pos["quantity"]))
        if qty <= 1e-12:
            return
        exit_price = raw_exit - slippage - spread / 2 if long_side else raw_exit + slippage + spread / 2
        gross = (exit_price - pos["entry"]) * qty * (1 if long_side else -1)
        fees = (pos["entry"] + exit_price) * qty * commission_pct / 100
        net = gross - fees
        cash += net
        pos["_gross"] += gross
        pos["_fees"] += fees
        pos["_net"] += net
        pos["remaining_quantity"] = max(0.0, qty - qty)
        pos.setdefault("partial_exits", []).append({
            "index": idx, "time": int(candle["time"]), "price": round(exit_price, 10),
            "quantity": round(qty, 10), "reason": reason,
            "gross_pnl": round(gross, 8), "fees": round(fees, 8), "net_pnl": round(net, 8),
        })
        initial_risk = abs(pos["entry"] - pos["initial_stop_loss"]) * pos["quantity"]
        trades.append({
            **{k: v for k, v in pos.items() if not k.startswith("_")},
            "exit_index": idx, "exit_time": int(candle["time"]),
            "exit": round(exit_price, 10), "exit_reason": reason,
            "gross_pnl": round(pos["_gross"], 8), "fees": round(pos["_fees"], 8),
            "net_pnl": round(pos["_net"], 8),
            "r_multiple": round(pos["_net"] / initial_risk, 6) if initial_risk else 0.0,
            "equity_after": round(cash, 8),
        })

    def close_partial(pos: dict[str, Any], candle: dict[str, Any], idx: int,
                      raw_exit: float, qty: float, level_index: int) -> None:
        """Realize a TP slice; BE stop becomes active on the next candle."""
        nonlocal cash
        long_side = pos["direction"] == "bullish"
        qty = min(float(qty), float(pos["remaining_quantity"]))
        exit_price = raw_exit - slippage - spread / 2 if long_side else raw_exit + slippage + spread / 2
        gross = (exit_price - pos["entry"]) * qty * (1 if long_side else -1)
        fees = (pos["entry"] + exit_price) * qty * commission_pct / 100
        net = gross - fees
        cash += net
        pos["_gross"] += gross
        pos["_fees"] += fees
        pos["_net"] += net
        pos["remaining_quantity"] = max(0.0, pos["remaining_quantity"] - qty)
        pos.setdefault("partial_exits", []).append({
            "index": idx, "time": int(candle["time"]), "price": round(exit_price, 10),
            "quantity": round(qty, 10), "reason": f"take_profit_{level_index + 1}",
            "gross_pnl": round(gross, 8), "fees": round(fees, 8), "net_pnl": round(net, 8),
        })
        pos["_next_tp"] += 1
        if level_index == 0 and pos["break_even_after_tp1"]:
            pos["stop_loss"] = pos["entry"]
        if pos["remaining_quantity"] <= 1e-12:
            initial_risk = abs(pos["entry"] - pos["initial_stop_loss"]) * pos["quantity"]
            trades.append({
                **{k: v for k, v in pos.items() if not k.startswith("_")},
                "exit_index": idx, "exit_time": int(candle["time"]),
                "exit": round(exit_price, 10), "exit_reason": f"take_profit_{level_index + 1}",
                "gross_pnl": round(pos["_gross"], 8), "fees": round(pos["_fees"], 8),
                "net_pnl": round(pos["_net"], 8),
                "r_multiple": round(pos["_net"] / initial_risk, 6) if initial_risk else 0.0,
                "equity_after": round(cash, 8),
            })

    for ts in timeline:
        bars = bars_by_time[ts]
        day, week = _period(ts)
        if day != day_key:
            day_key = day
            day_start = mark_to_market(last_prices)
        if week != week_key:
            week_key = week
            week_start = mark_to_market(last_prices)

        # Resolve existing positions using the current bar for their symbol.
        for pos in list(active):
            current = bars.get(pos["symbol"])
            if current is None:
                continue
            idx, candle = current
            long_side = pos["direction"] == "bullish"
            stop_hit = float(candle["low"]) <= pos["stop_loss"] if long_side else float(candle["high"]) >= pos["stop_loss"]
            levels = pos.get("take_profits") or []
            if stop_hit:
                close_position(pos, candle, idx, pos["stop_loss"], "stop_loss")
                active.remove(pos)
            elif levels:
                level_index = pos["_next_tp"]
                if level_index < len(levels):
                    level = levels[level_index]
                    hit = float(candle["high"]) >= level["price"] if long_side else float(candle["low"]) <= level["price"]
                    if hit:
                        qty = pos["quantity"] * level["fraction"]
                        if level_index == len(levels) - 1:
                            qty = pos["remaining_quantity"]
                        close_partial(pos, candle, idx, level["price"], qty, level_index)
                        if pos["remaining_quantity"] <= 1e-12:
                            active.remove(pos)
            else:
                target_hit = float(candle["high"]) >= pos["take_profit"] if long_side else float(candle["low"]) <= pos["take_profit"]
                if target_hit:
                    close_position(pos, candle, idx, pos["take_profit"], "take_profit")
                    active.remove(pos)

        # At the timestamp open, value existing positions with current opens
        # where available and last known closes for all other symbols.
        open_prices = dict(last_prices)
        for symbol, (_, candle) in bars.items():
            open_prices[symbol] = float(candle["open"])

        for sig in sorted(entries_by_time.get(ts, []), key=lambda x: x["_order"]):
            current_equity = mark_to_market(open_prices)
            peak = max(peak, current_equity)
            daily_loss = max(0.0, (day_start - current_equity) / day_start * 100) if day_start else 0.0
            weekly_loss = max(0.0, (week_start - current_equity) / week_start * 100) if week_start else 0.0
            current_dd = max(0.0, (peak - current_equity) / peak * 100) if peak else 0.0
            blocker = None
            if len(active) >= max_open_trades:
                blocker = "max_open_trades"
                blocks["capacity"] += 1
            elif max_daily_loss_pct > 0 and daily_loss >= max_daily_loss_pct:
                blocker = "daily_loss_limit"
                blocks["daily"] += 1
            elif max_weekly_loss_pct > 0 and weekly_loss >= max_weekly_loss_pct:
                blocker = "weekly_loss_limit"
                blocks["weekly"] += 1
            elif max_drawdown_pct > 0 and current_dd >= max_drawdown_pct:
                blocker = "max_drawdown_limit"
                blocks["drawdown"] += 1
            if blocker:
                rejected.append({"signal_index": sig["signal_index"], "symbol": sig["symbol"], "reason": blocker})
                continue

            _, candle = bars[sig["symbol"]]
            raw_open = float(candle["open"])
            long_side = sig["direction"] == "bullish"
            entry = raw_open + slippage + spread / 2 if long_side else raw_open - slippage - spread / 2
            stop, target = sig["stop_loss"], sig["take_profit"]
            valid = stop < entry < target if long_side else target < entry < stop
            if not valid:
                rejected.append({"signal_index": sig["signal_index"], "symbol": sig["symbol"], "reason": "invalid_levels_at_entry"})
                continue
            pos = {k: v for k, v in sig.items() if not k.startswith("_")}
            pos.update({
                "entry_time": ts, "entry": entry, "initial_stop_loss": stop,
                "remaining_quantity": qty, "take_profits": sig.get("take_profits") or [],
                "break_even_after_tp1": bool(sig.get("break_even_after_tp1", True)),
                "_next_tp": 0, "_gross": 0.0, "_fees": 0.0, "_net": 0.0,
            })
            active.append(pos)

            # Newly opened positions are exposed to the remainder of this OHLC bar.
            idx, candle = bars[sig["symbol"]]
            stop_hit = float(candle["low"]) <= stop if long_side else float(candle["high"]) >= stop
            levels = pos.get("take_profits") or []
            target_hit = float(candle["high"]) >= target if long_side else float(candle["low"]) <= target
            if stop_hit:
                close_position(pos, candle, idx, stop, "stop_loss")
                active.remove(pos)
            elif levels:
                first = levels[0]
                first_hit = float(candle["high"]) >= first["price"] if long_side else float(candle["low"]) <= first["price"]
                if first_hit:
                    close_partial(pos, candle, idx, first["price"], qty * first["fraction"], 0)
                    if pos["remaining_quantity"] <= 1e-12:
                        active.remove(pos)
            elif target_hit:
                close_position(pos, candle, idx, target, "take_profit")
                active.remove(pos)

        # Update close marks after all bars at this timestamp have completed.
        for symbol, (_, candle) in bars.items():
            last_prices[symbol] = float(candle["close"])
        marked = mark_to_market(last_prices)
        peak = max(peak, marked)
        max_dd = max(max_dd, (peak - marked) / peak * 100 if peak else 0.0)
        equity_curve.append({
            "time": ts, "equity": round(marked, 8),
            "cash_equity": round(cash, 8), "open_positions": len(active),
        })

    # Close any positions still open at the final known close of their symbol.
    final_time = timeline[-1]
    for pos in list(active):
        symbol = pos["symbol"]
        candle = normalized[symbol][-1]
        idx = len(normalized[symbol]) - 1
        close_position(pos, candle, idx, float(candle["close"]), "end_of_data")
        active.remove(pos)
    if equity_curve:
        equity_curve[-1]["equity"] = round(cash, 8)
        equity_curve[-1]["cash_equity"] = round(cash, 8)
        equity_curve[-1]["open_positions"] = 0

    wins = [t for t in trades if t["net_pnl"] > 0]
    losses = [t for t in trades if t["net_pnl"] < 0]
    gross_profit = sum(t["net_pnl"] for t in wins)
    gross_loss = abs(sum(t["net_pnl"] for t in losses))
    per_symbol: dict[str, Any] = {}
    for symbol in normalized:
        items = [t for t in trades if t["symbol"] == symbol]
        sw = [t for t in items if t["net_pnl"] > 0]
        sl = [t for t in items if t["net_pnl"] < 0]
        per_symbol[symbol] = {
            "trade_count": len(items), "wins": len(sw), "losses": len(sl),
            "net_pnl": round(sum(t["net_pnl"] for t in items), 8),
            "win_rate_pct": round(len(sw) / len(items) * 100, 4) if items else None,
        }

    return {
        "simulation_mode": "shared_portfolio",
        "symbol_count": len(normalized), "symbols": list(normalized),
        "initial_equity": round(initial_equity, 8),
        "ending_equity": round(cash, 8), "net_pnl": round(cash - initial_equity, 8),
        "trade_count": len(trades), "wins": len(wins), "losses": len(losses),
        "win_rate_pct": round(len(wins) / len(trades) * 100, 4) if trades else None,
        "profit_factor": round(gross_profit / gross_loss, 6) if gross_loss else ("infinite" if wins else None),
        "max_drawdown_pct": round(max_dd, 6),
        "expectancy_per_trade": round(sum(t["net_pnl"] for t in trades) / len(trades), 8) if trades else None,
        "per_symbol": per_symbol, "trades": sorted(trades, key=lambda t: (t["entry_time"], t["symbol"], t["entry_index"])),
        "rejected_signals": rejected,
        "risk_controls": {
            "max_open_trades": max_open_trades,
            "max_daily_loss_pct": max_daily_loss_pct,
            "max_weekly_loss_pct": max_weekly_loss_pct,
            "max_drawdown_pct": max_drawdown_pct,
            "blocked_by_capacity": blocks["capacity"],
            "blocked_by_daily_loss": blocks["daily"],
            "blocked_by_weekly_loss": blocks["weekly"],
            "blocked_by_drawdown": blocks["drawdown"],
        },
        "equity_curve": equity_curve,
        "assumptions": {
            "entry": "signal at candle i enters at candle i+1 open on a shared UTC timeline",
            "intrabar_order": "stop is assumed before target when both are touched in the same OHLC bar",
            "equity_marking": "mark-to-market using latest known close per symbol; intrabar drawdown is not tick-accurate",
            "period_limits": "UTC calendar day and ISO week; shared across all symbols",
            "commission_pct": commission_pct, "spread_price_units": spread,
            "slippage_price_units": slippage,
            "capital_model": "shared equity; no broker-specific margin, leverage, contract multiplier, or notional reservation model",
            "partial_take_profit": "one TP level maximum per OHLC candle; stop is checked first; break-even applies from the candle after TP1",
        },
        "estimated_win_probability": None,
        "execution_allowed": False,
    }
