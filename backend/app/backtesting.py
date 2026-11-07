from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any


def _utc_period(timestamp: int) -> tuple[str, str]:
    dt = datetime.fromtimestamp(timestamp, tz=timezone.utc)
    iso = dt.isocalendar()
    return dt.date().isoformat(), f"{iso.year}-W{iso.week:02d}"


def run_bar_backtest(
    candles: list[dict[str, Any]],
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
    """Conservative multi-position OHLC replay.

    A signal at candle i may enter only at candle i+1 open. Multiple signals
    at the same index are retained and processed in input order. If stop and
    target are both touched in one candle, stop is assumed first.

    Equity is marked to market at each candle close. Intrabar path is unknown,
    so drawdown is close-marked, not tick-accurate. All timestamps are grouped
    into UTC days/weeks for loss limits.
    """
    if len(candles) < 3:
        raise ValueError("At least 3 candles are required")
    if not math.isfinite(initial_equity) or initial_equity <= 0:
        raise ValueError("initial_equity must be finite and positive")
    if any(not math.isfinite(x) or x < 0 for x in (spread, slippage, commission_pct)):
        raise ValueError("Trading costs must be finite and nonnegative")
    if commission_pct > 5:
        raise ValueError("commission_pct cannot exceed 5")
    if not isinstance(max_open_trades, int) or not 1 <= max_open_trades <= 100:
        raise ValueError("max_open_trades must be between 1 and 100")
    for name, value in (
        ("max_daily_loss_pct", max_daily_loss_pct),
        ("max_weekly_loss_pct", max_weekly_loss_pct),
        ("max_drawdown_pct", max_drawdown_pct),
    ):
        if not math.isfinite(value) or not 0 <= value <= 100:
            raise ValueError(f"{name} must be between 0 and 100")

    times: list[int] = []
    for i, candle in enumerate(candles):
        try:
            timestamp = int(candle["time"])
            o, h, lo, cl = (float(candle[k]) for k in ("open", "high", "low", "close"))
        except (KeyError, TypeError, ValueError, OverflowError) as exc:
            raise ValueError(f"Invalid candle at index {i}") from exc
        if not all(math.isfinite(x) and x > 0 for x in (o, h, lo, cl)):
            raise ValueError(f"Invalid OHLC values at candle {i}")
        if not lo <= min(o, cl) <= max(o, cl) <= h:
            raise ValueError(f"OHLC invariant violated at candle {i}")
        times.append(timestamp)
    if times != sorted(times) or len(times) != len(set(times)):
        raise ValueError("Candles must be strictly chronological without duplicates")

    signals_by_index: dict[int, list[dict[str, Any]]] = {}
    for input_order, raw in enumerate(signals):
        try:
            idx = int(raw["index"])
            direction = str(raw["direction"]).lower()
            stop = float(raw["stop_loss"])
            target = float(raw["take_profit"])
            qty = float(raw.get("quantity", 1.0))
        except (KeyError, TypeError, ValueError, OverflowError) as exc:
            raise ValueError("Invalid signal fields") from exc
        if idx < 0 or idx >= len(candles) - 1:
            raise ValueError("Signal index must have a following candle for entry")
        if direction not in ("bullish", "bearish"):
            raise ValueError("Signal direction must be bullish or bearish")
        if not all(math.isfinite(x) and x > 0 for x in (stop, target, qty)):
            raise ValueError("Stop, target and quantity must be finite and positive")
        normalized = {
            **raw, "index": idx, "direction": direction,
            "stop_loss": stop, "take_profit": target, "quantity": qty,
            "_input_order": input_order,
        }
        signals_by_index.setdefault(idx, []).append(normalized)

    cash_equity = float(initial_equity)
    peak_equity = float(initial_equity)
    max_dd = 0.0
    active: list[dict[str, Any]] = []
    trades: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    equity_curve: list[dict[str, Any]] = []
    day_key: str | None = None
    week_key: str | None = None
    day_start_equity = float(initial_equity)
    week_start_equity = float(initial_equity)
    daily_blocks = 0
    weekly_blocks = 0
    drawdown_blocks = 0
    capacity_blocks = 0

    def mark_to_market(close_price: float) -> float:
        unrealized = 0.0

        for position in active:
            long_side = position["direction"] == "bullish"
            side = 1.0 if long_side else -1.0

            estimated_exit = (
                close_price - slippage - spread / 2
                if long_side
                else close_price + slippage + spread / 2
            )

            gross = (
                (estimated_exit - position["entry"])
                * position["quantity"]
                * side
            )

            estimated_fees = (
                position["entry"] + estimated_exit
            ) * position["quantity"] * commission_pct / 100

            unrealized += gross - estimated_fees

        return cash_equity + unrealized

    def close_position(position: dict[str, Any], candle: dict[str, Any],
                       exit_index: int, raw_exit: float, reason: str) -> None:
        nonlocal cash_equity
        long_side = position["direction"] == "bullish"
        exit_price = (
            raw_exit - slippage - spread / 2
            if long_side else raw_exit + slippage + spread / 2
        )
        gross = (exit_price - position["entry"]) * position["quantity"] * (
            1 if long_side else -1
        )
        fees = (position["entry"] + exit_price) * position["quantity"] * commission_pct / 100
        net = gross - fees
        risk_cash = abs(position["entry"] - position["stop_loss"]) * position["quantity"]
        cash_equity += net
        trades.append({
            **{k: v for k, v in position.items() if not k.startswith("_")},
            "exit_index": exit_index,
            "exit_time": int(candle["time"]),
            "exit": round(exit_price, 10),
            "exit_reason": reason,
            "gross_pnl": round(gross, 8),
            "fees": round(fees, 8),
            "net_pnl": round(net, 8),
            "r_multiple": round(net / risk_cash, 6) if risk_cash else 0.0,
            "equity_after": round(cash_equity, 8),
        })

    for i, candle in enumerate(candles):
        timestamp = int(candle["time"])
        current_day, current_week = _utc_period(timestamp)
        if current_day != day_key:
            day_key = current_day
            day_start_equity = mark_to_market(float(candles[i - 1]["close"])) if i else cash_equity
        if current_week != week_key:
            week_key = current_week
            week_start_equity = mark_to_market(float(candles[i - 1]["close"])) if i else cash_equity

        # Resolve all currently open positions against this candle.
        remaining: list[dict[str, Any]] = []
        for position in active:
            long_side = position["direction"] == "bullish"
            stop_hit = (
                float(candle["low"]) <= position["stop_loss"]
                if long_side else float(candle["high"]) >= position["stop_loss"]
            )
            target_hit = (
                float(candle["high"]) >= position["take_profit"]
                if long_side else float(candle["low"]) <= position["take_profit"]
            )
            if stop_hit:
                close_position(position, candle, i, position["stop_loss"], "stop_loss")
            elif target_hit:
                close_position(position, candle, i, position["take_profit"], "take_profit")
            elif i == len(candles) - 1:
                close_position(position, candle, i, float(candle["close"]), "end_of_data")
            else:
                remaining.append(position)
        active = remaining

        # Signals from the previous candle enter at this candle's open.
        newly_opened: list[dict[str, Any]] = []
        for signal in signals_by_index.get(i - 1, []):
            current_equity = mark_to_market(float(candle["open"]))
            daily_loss = max(0.0, (day_start_equity - current_equity) / day_start_equity * 100)
            weekly_loss = max(0.0, (week_start_equity - current_equity) / week_start_equity * 100)
            current_dd = max(0.0, (peak_equity - current_equity) / peak_equity * 100)

            blocker = None
            if len(active) >= max_open_trades:
                blocker = "max_open_trades"
                capacity_blocks += 1
            elif max_daily_loss_pct > 0 and daily_loss >= max_daily_loss_pct:
                blocker = "daily_loss_limit"
                daily_blocks += 1
            elif max_weekly_loss_pct > 0 and weekly_loss >= max_weekly_loss_pct:
                blocker = "weekly_loss_limit"
                weekly_blocks += 1
            elif max_drawdown_pct > 0 and current_dd >= max_drawdown_pct:
                blocker = "max_drawdown_limit"
                drawdown_blocks += 1

            if blocker:
                rejected.append({
                    "signal_index": signal["index"],
                    "symbol": signal.get("symbol"),
                    "reason": blocker,
                })
                continue

            raw_open = float(candle["open"])
            half_spread = spread / 2
            long_side = signal["direction"] == "bullish"
            entry = raw_open + slippage + half_spread if long_side else raw_open - slippage - half_spread
            stop, target = signal["stop_loss"], signal["take_profit"]
            valid = stop < entry < target if long_side else target < entry < stop
            if not valid:
                rejected.append({
                    "signal_index": signal["index"],
                    "symbol": signal.get("symbol"),
                    "reason": "invalid_levels_at_entry",
                })
                continue

            position = {
                "symbol": signal.get("symbol"),
                "direction": signal["direction"],
                "signal_index": signal["index"],
                "entry_index": i,
                "entry_time": timestamp,
                "entry": entry,
                "stop_loss": stop,
                "take_profit": target,
                "quantity": signal["quantity"],
                "_input_order": signal["_input_order"],
            }
            active.append(position)
            newly_opened.append(position)

        # A position entered at this candle's open is exposed to this candle's
        # high/low too. Stop is conservatively evaluated before target.
        for position in newly_opened:
            if position not in active:
                continue
            long_side = position["direction"] == "bullish"
            stop_hit = (
                float(candle["low"]) <= position["stop_loss"]
                if long_side else float(candle["high"]) >= position["stop_loss"]
            )
            target_hit = (
                float(candle["high"]) >= position["take_profit"]
                if long_side else float(candle["low"]) <= position["take_profit"]
            )
            if stop_hit:
                close_position(position, candle, i, position["stop_loss"], "stop_loss")
                active.remove(position)
            elif target_hit:
                close_position(position, candle, i, position["take_profit"], "take_profit")
                active.remove(position)
            elif i == len(candles) - 1:
                close_position(position, candle, i, float(candle["close"]), "end_of_data")
                active.remove(position)

        close = float(candle["close"])
        marked_equity = mark_to_market(close)
        peak_equity = max(peak_equity, marked_equity)
        max_dd = max(max_dd, (peak_equity - marked_equity) / peak_equity * 100 if peak_equity else 0.0)
        equity_curve.append({
            "time": timestamp,
            "equity": round(marked_equity, 8),
            "cash_equity": round(cash_equity, 8),
            "open_positions": len(active),
        })

    wins = [trade for trade in trades if trade["net_pnl"] > 0]
    losses = [trade for trade in trades if trade["net_pnl"] < 0]
    gross_profit = sum(trade["net_pnl"] for trade in wins)
    gross_loss = abs(sum(trade["net_pnl"] for trade in losses))
    return {
        "trade_count": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate_pct": round(len(wins) / len(trades) * 100, 4) if trades else None,
        "profit_factor": round(gross_profit / gross_loss, 6) if gross_loss else (None if not wins else "infinite"),
        "net_pnl": round(cash_equity - initial_equity, 8),
        "ending_equity": round(cash_equity, 8),
        "max_drawdown_pct": round(max_dd, 6),
        "expectancy_per_trade": round(sum(t["net_pnl"] for t in trades) / len(trades), 8) if trades else None,
        "average_r": round(sum(t["r_multiple"] for t in trades) / len(trades), 6) if trades else None,
        "trades": trades,
        "rejected_signals": rejected,
        "risk_controls": {
            "max_open_trades": max_open_trades,
            "max_daily_loss_pct": max_daily_loss_pct,
            "max_weekly_loss_pct": max_weekly_loss_pct,
            "max_drawdown_pct": max_drawdown_pct,
            "blocked_by_capacity": capacity_blocks,
            "blocked_by_daily_loss": daily_blocks,
            "blocked_by_weekly_loss": weekly_blocks,
            "blocked_by_drawdown": drawdown_blocks,
        },
        "equity_curve": equity_curve,
        "assumptions": {
            "entry": "next candle open after signal index; adverse slippage and half-spread applied",
            "intrabar_order": "stop is assumed before target when both are touched in the same OHLC bar",
            "equity_marking": "mark-to-market at candle close; intrabar drawdown is not tick-accurate",
            "period_limits": "UTC calendar day and ISO week",
            "commission_pct": commission_pct,
            "spread_price_units": spread,
            "slippage_price_units": slippage,
            "signal_generation": "signals supplied by caller; this endpoint does not generate strategy signals",
        },
        "estimated_win_probability": None,
        "execution_allowed": False,
    }
