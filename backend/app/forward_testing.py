"""Tick-driven, tenant-scoped forward testing. This module never sends broker orders."""
from __future__ import annotations

import math
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import and_, or_, select, func

from .database import get_session_factory
from .db_models import (
    BacktestRun, BrokerAccount, ForwardTestEvent, ForwardTestRun, ForwardTestTrade,
    Portfolio, Signal,
)

ACTIVE_SIGNAL_STATUSES = ("WAITING_ENTRY", "OPEN", "TP1_HIT", "TP2_HIT")
ACTIVE_TRADE_STATUSES = ("pending_entry", "open", "tp1_hit", "tp2_hit")
TERMINAL_TRADE_STATUSES = ("tp3_hit", "stopped")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _event_datetime(event_time_ms: int) -> datetime:
    return datetime.fromtimestamp(event_time_ms / 1000.0, tz=timezone.utc)


def normalize_symbols(symbols: list[str]) -> list[str]:
    if not symbols:
        raise ValueError("At least one symbol is required")
    normalized = sorted({str(s).strip().upper() for s in symbols})
    if len(normalized) > 50:
        raise ValueError("A forward-test run supports at most 50 symbols")
    for symbol in normalized:
        if not symbol or len(symbol) > 30 or not symbol.replace("_", "").isalnum():
            raise ValueError(f"Invalid symbol: {symbol!r}")
    return normalized


def adverse_fill(market_price: float, direction: str, is_entry: bool, slippage_bps: float) -> float:
    """Apply adverse slippage: worse for the simulated trader on both sides."""
    if not all(math.isfinite(float(x)) for x in (market_price, slippage_bps)):
        raise ValueError("Price and slippage must be finite")
    if market_price <= 0 or slippage_bps < 0:
        raise ValueError("Price must be positive and slippage non-negative")
    if direction not in ("long", "short"):
        raise ValueError("direction must be long or short")
    rate = slippage_bps / 10000.0
    buy = (direction == "long" and is_entry) or (direction == "short" and not is_entry)
    return market_price * (1.0 + rate if buy else 1.0 - rate)


def entry_triggered(direction: str, market_price: float, planned_entry: float) -> bool:
    if direction == "long":
        return market_price <= planned_entry
    if direction == "short":
        return market_price >= planned_entry
    raise ValueError("direction must be long or short")


def exit_triggered(direction: str, market_price: float, stop: float, target: float) -> tuple[bool, bool]:
    """Return (stop_hit, any_target_hit); caller gives stop precedence on gap ticks."""
    if direction == "long":
        return market_price <= stop, market_price >= target
    if direction == "short":
        return market_price >= stop, market_price <= target
    raise ValueError("direction must be long or short")


def _trade_dict(row: ForwardTestTrade) -> dict[str, Any]:
    return {
        "id": row.id, "run_id": row.run_id, "signal_id": row.signal_id,
        "symbol": row.symbol, "direction": row.direction, "status": row.status,
        "quality_score": row.quality_score, "planned_entry": row.planned_entry,
        "actual_entry": row.actual_entry, "stop_loss": row.stop_loss,
        "take_profits": [row.tp1, row.tp2, row.tp3],
        "quantity": row.quantity, "remaining_quantity": row.remaining_quantity,
        "risk_cash": row.risk_cash, "realized_pnl": row.realized_pnl,
        "fees_paid": row.fees_paid, "last_price": row.last_price,
        "entry_time": row.entry_time.isoformat() if row.entry_time else None,
        "closed_at": row.closed_at.isoformat() if row.closed_at else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def _run_dict(row: ForwardTestRun) -> dict[str, Any]:
    return {
        "id": row.id, "portfolio_id": row.portfolio_id, "account_id": row.account_id,
        "status": row.status, "symbols": row.symbols,
        "initial_equity": row.initial_equity,
        "realized_equity": float(row.initial_equity) + float(row.realized_pnl),
        "realized_pnl": row.realized_pnl, "fees_paid": row.fees_paid,
        "risk_per_trade_pct": row.risk_per_trade_pct,
        "min_quality_score": row.min_quality_score,
        "commission_pct": row.commission_pct, "slippage_bps": row.slippage_bps,
        "include_existing_signals": row.include_existing_signals,
        "started_at": row.started_at.isoformat(),
        "stopped_at": row.stopped_at.isoformat() if row.stopped_at else None,
    }


def start_forward_run(
    user_id: str,
    portfolio_id: str,
    account_id: str,
    symbols: list[str],
    risk_per_trade_pct: float = 0.5,
    min_quality_score: int = 70,
    commission_pct: float = 0.04,
    slippage_bps: float = 2.0,
    include_existing_signals: bool = False,
) -> dict[str, Any]:
    symbols = normalize_symbols(symbols)
    vals = (risk_per_trade_pct, commission_pct, slippage_bps)
    if not all(math.isfinite(float(v)) for v in vals):
        raise ValueError("Forward-test settings must be finite")
    if not 0 < risk_per_trade_pct <= 5:
        raise ValueError("risk_per_trade_pct must be in (0, 5]")
    if not 0 <= min_quality_score <= 100:
        raise ValueError("min_quality_score must be between 0 and 100")
    if not 0 <= commission_pct <= 1:
        raise ValueError("commission_pct must be between 0 and 1")
    if not 0 <= slippage_bps <= 500:
        raise ValueError("slippage_bps must be between 0 and 500")

    db = get_session_factory()()
    try:
        portfolio = db.scalar(select(Portfolio).where(
            Portfolio.id == portfolio_id, Portfolio.user_id == user_id
        ).with_for_update())
        if portfolio is None:
            raise LookupError("Portfolio not found")
        account = db.scalar(select(BrokerAccount).where(
            BrokerAccount.id == account_id,
            BrokerAccount.user_id == user_id,
            BrokerAccount.portfolio_id == portfolio_id,
            BrokerAccount.mode == "paper",
        ))
        if account is None:
            raise LookupError("Paper account not found for this portfolio")
        if account.broker != "binance":
            raise ValueError("Forward testing currently requires a Binance paper account; the MT5 market-data bridge is not configured")
        if risk_per_trade_pct > float(portfolio.max_trade_risk_pct):
            raise ValueError("Forward-test per-trade risk exceeds portfolio max_trade_risk_pct")
        active = db.scalar(select(ForwardTestRun.id).where(
            ForwardTestRun.user_id == user_id,
            ForwardTestRun.portfolio_id == portfolio_id,
            ForwardTestRun.status.in_(("active", "stopping")),
        ).limit(1))
        if active:
            raise ValueError("This portfolio already has an active forward-test run")
        now = _now()
        row = ForwardTestRun(
            id=str(uuid.uuid4()), user_id=user_id, portfolio_id=portfolio_id,
            account_id=account_id, status="active", symbols=symbols,
            initial_equity=float(portfolio.initial_equity),
            risk_per_trade_pct=float(risk_per_trade_pct),
            min_quality_score=int(min_quality_score),
            commission_pct=float(commission_pct), slippage_bps=float(slippage_bps),
            include_existing_signals=bool(include_existing_signals),
            started_at=now, created_at=now,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return _run_dict(row)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def stop_forward_run(user_id: str, run_id: str) -> dict[str, Any]:
    db = get_session_factory()()
    try:
        run = db.scalar(select(ForwardTestRun).where(
            ForwardTestRun.id == run_id, ForwardTestRun.user_id == user_id
        ).with_for_update())
        if run is None:
            raise LookupError("Forward-test run not found")
        if run.status == "active":
            run.status = "stopping"
        remaining = db.scalar(select(func.count()).select_from(ForwardTestTrade).where(
            ForwardTestTrade.run_id == run_id,
            ForwardTestTrade.status.in_(ACTIVE_TRADE_STATUSES),
        )) or 0
        if not remaining:
            run.status = "stopped"
            run.stopped_at = _now()
        db.commit()
        db.refresh(run)
        return _run_dict(run)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def list_forward_runs(user_id: str, portfolio_id: str, limit: int = 20) -> list[dict[str, Any]]:
    if not 1 <= limit <= 100:
        raise ValueError("limit must be between 1 and 100")
    db = get_session_factory()()
    try:
        owned = db.scalar(select(Portfolio.id).where(
            Portfolio.id == portfolio_id, Portfolio.user_id == user_id
        ))
        if not owned:
            raise LookupError("Portfolio not found")
        rows = db.scalars(select(ForwardTestRun).where(
            ForwardTestRun.user_id == user_id,
            ForwardTestRun.portfolio_id == portfolio_id,
        ).order_by(ForwardTestRun.created_at.desc()).limit(limit)).all()
        return [_run_dict(r) for r in rows]
    finally:
        db.close()


def list_forward_trades(user_id: str, run_id: str, status: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
    if not 1 <= limit <= 500:
        raise ValueError("limit must be between 1 and 500")
    db = get_session_factory()()
    try:
        owned = db.scalar(select(ForwardTestRun.id).where(
            ForwardTestRun.id == run_id, ForwardTestRun.user_id == user_id
        ))
        if not owned:
            raise LookupError("Forward-test run not found")
        stmt = select(ForwardTestTrade).where(
            ForwardTestTrade.run_id == run_id, ForwardTestTrade.user_id == user_id
        )
        if status:
            stmt = stmt.where(ForwardTestTrade.status == status.lower())
        rows = db.scalars(stmt.order_by(ForwardTestTrade.created_at.desc()).limit(limit)).all()
        return [_trade_dict(r) for r in rows]
    finally:
        db.close()


def forward_summary(user_id: str, run_id: str) -> dict[str, Any]:
    db = get_session_factory()()
    try:
        run = db.scalar(select(ForwardTestRun).where(
            ForwardTestRun.id == run_id, ForwardTestRun.user_id == user_id
        ))
        if run is None:
            raise LookupError("Forward-test run not found")
        trades = db.scalars(select(ForwardTestTrade).where(
            ForwardTestTrade.run_id == run_id, ForwardTestTrade.user_id == user_id
        )).all()
        closed = [t for t in trades if t.status in TERMINAL_TRADE_STATUSES]
        wins = sum(1 for t in closed if float(t.realized_pnl) > 0)
        unrealized = 0.0
        for trade in trades:
            if trade.status in ("open", "tp1_hit", "tp2_hit") and trade.actual_entry and trade.last_price and trade.remaining_quantity > 0:
                direction = 1.0 if trade.direction == "long" else -1.0
                qty = float(trade.remaining_quantity)
                estimated_exit = adverse_fill(
                    float(trade.last_price), trade.direction, False, run.slippage_bps
                )
                gross = (estimated_exit - float(trade.actual_entry)) * qty * direction
                estimated_fee = _charge_fee(estimated_exit * qty, run.commission_pct)
                unrealized += gross - estimated_fee
        events = db.scalars(select(ForwardTestEvent).join(
            ForwardTestTrade, ForwardTestTrade.id == ForwardTestEvent.trade_id
        ).where(
            ForwardTestTrade.run_id == run_id,
            ForwardTestTrade.user_id == user_id,
        )).all()
        today = _now().date()
        current_iso_week = today.isocalendar()[:2]
        daily_pnl = sum(float(e.pnl) for e in events if e.event_time.date() == today)
        weekly_pnl = sum(
            float(e.pnl) for e in events
            if e.event_time.date().isocalendar()[:2] == current_iso_week
        )
        return {
            "run": _run_dict(run),
            "daily_realized_pnl_utc": daily_pnl,
            "weekly_realized_pnl_utc": weekly_pnl,
            "unrealized_pnl_estimate": unrealized,
            "estimated_current_equity": float(run.initial_equity) + float(run.realized_pnl) + unrealized,
            "trade_count": len(trades),
            "pending_entry": sum(t.status == "pending_entry" for t in trades),
            "open_positions": sum(t.status in ("open", "tp1_hit", "tp2_hit") for t in trades),
            "closed_trades": len(closed),
            "winning_trades": wins,
            "losing_trades": len(closed) - wins,
            "win_rate_pct": (wins / len(closed) * 100.0) if closed else None,
            "realized_pnl": float(run.realized_pnl),
            "fees_paid": float(run.fees_paid),
            "net_return_pct": (float(run.realized_pnl) / float(run.initial_equity) * 100.0),
            "methodology": "Tick-driven paper fills; partial exits at observed market ticks; adverse slippage and commissions included.",
            "estimated_win_probability": None,
            "live_execution_allowed": False,
        }
    finally:
        db.close()



def list_forward_events(user_id: str, trade_id: str, limit: int = 200) -> list[dict[str, Any]]:
    from .db_models import ForwardTestEvent
    if not 1 <= limit <= 500:
        raise ValueError("limit must be between 1 and 500")
    db = get_session_factory()()
    try:
        owned = db.scalar(select(ForwardTestTrade.id).where(
            ForwardTestTrade.id == trade_id, ForwardTestTrade.user_id == user_id
        ))
        if not owned:
            raise LookupError("Forward-test trade not found")
        rows = db.scalars(select(ForwardTestEvent).join(
            ForwardTestTrade, ForwardTestTrade.id == ForwardTestEvent.trade_id
        ).where(
            ForwardTestEvent.trade_id == trade_id,
            ForwardTestTrade.user_id == user_id,
        ).order_by(ForwardTestEvent.id.asc()).limit(limit)).all()
        return [{
            "id": r.id, "event_type": r.event_type,
            "market_price": r.market_price, "fill_price": r.fill_price,
            "quantity": r.quantity, "pnl": r.pnl, "fee": r.fee,
            "event_time_ms": r.event_time_ms,
            "event_time": r.event_time.isoformat(),
            "details": r.details_json,
        } for r in rows]
    finally:
        db.close()



def compare_forward_to_backtest(user_id: str, run_id: str, backtest_run_id: str) -> dict[str, Any]:
    db = get_session_factory()()
    try:
        run = db.scalar(select(ForwardTestRun).where(
            ForwardTestRun.id == run_id, ForwardTestRun.user_id == user_id
        ))
        if run is None:
            raise LookupError("Forward-test run not found")
        backtest = db.scalar(select(BacktestRun).where(
            BacktestRun.id == backtest_run_id,
            BacktestRun.user_id == user_id,
            BacktestRun.portfolio_id == run.portfolio_id,
        ))
        if backtest is None:
            raise LookupError("Backtest run not found for this portfolio")
        trades = db.scalars(select(ForwardTestTrade).where(
            ForwardTestTrade.run_id == run_id,
            ForwardTestTrade.user_id == user_id,
        )).all()
        closed = [t for t in trades if t.status in TERMINAL_TRADE_STATUSES]
        wins = sum(float(t.realized_pnl) > 0 for t in closed)
        forward_pnl = float(run.realized_pnl)
        result = backtest.result_json or {}
        backtest_pnl = result.get("net_pnl")
        return {
            "forward_run_id": run_id,
            "backtest_run_id": backtest_run_id,
            "same_portfolio": True,
            "backtest": {
                "trade_count": result.get("trade_count"),
                "net_pnl": backtest_pnl,
                "win_rate_pct": result.get("win_rate_pct"),
                "max_drawdown_pct": result.get("max_drawdown_pct"),
            },
            "forward_test": {
                "trade_count": len(closed),
                "net_pnl": forward_pnl,
                "win_rate_pct": wins / len(closed) * 100.0 if closed else None,
                "fees_paid": float(run.fees_paid),
            },
            "pnl_difference_forward_minus_backtest": (
                forward_pnl - float(backtest_pnl)
                if isinstance(backtest_pnl, (int, float)) and math.isfinite(float(backtest_pnl))
                else None
            ),
            "interpretation": "Descriptive comparison only. Backtest OHLC fills and live-tick paper fills use different execution paths and may cover different market periods.",
            "estimated_win_probability": None,
            "live_execution_allowed": False,
        }
    finally:
        db.close()


def active_forward_symbols() -> list[str]:
    db = get_session_factory()()
    try:
        rows = db.scalars(select(ForwardTestRun).where(
            ForwardTestRun.status.in_(("active", "stopping"))
        )).all()
        return sorted({symbol for run in rows for symbol in (run.symbols or [])})
    finally:
        db.close()


def _add_event(db, trade, event_type: str, market_price: float, event_time_ms: int,
               fill_price: float | None = None, quantity: float = 0.0,
               pnl: float = 0.0, fee: float = 0.0, details: dict | None = None):
    db.add(ForwardTestEvent(
        trade_id=trade.id, event_type=event_type, market_price=market_price,
        fill_price=fill_price, quantity=quantity, pnl=pnl, fee=fee,
        event_time_ms=event_time_ms, event_time=_event_datetime(event_time_ms),
        details_json=details or {},
    ))


def _charge_fee(notional: float, commission_pct: float) -> float:
    return abs(notional) * commission_pct / 100.0


def _record_exit(db, run, trade, market_price: float, event_time_ms: int,
                 quantity: float, event_type: str, details: dict | None = None):
    direction = 1.0 if trade.direction == "long" else -1.0
    fill = adverse_fill(market_price, trade.direction, False, run.slippage_bps)
    gross = (fill - float(trade.actual_entry)) * quantity * direction
    fee = _charge_fee(fill * quantity, run.commission_pct)
    net = gross - fee
    trade.realized_pnl = float(trade.realized_pnl) + net
    trade.fees_paid = float(trade.fees_paid) + fee
    trade.remaining_quantity = max(0.0, float(trade.remaining_quantity) - quantity)
    run.realized_pnl = float(run.realized_pnl) + net
    run.fees_paid = float(run.fees_paid) + fee
    _add_event(db, trade, event_type, market_price, event_time_ms, fill, quantity, net, fee, details)
    return net


def _process_trade_tick(db, run, trade, market_price: float, event_time_ms: int, event_id: str | None):
    previous_ms = int(trade.last_event_time_ms or 0)
    if event_time_ms < previous_ms:
        return
    if event_id and trade.last_event_id == event_id:
        return
    if not event_id and event_time_ms <= previous_ms:
        return
    trade.last_event_time_ms = event_time_ms
    trade.last_event_id = event_id
    trade.last_price = market_price

    if trade.status == "pending_entry":
        if not entry_triggered(trade.direction, market_price, trade.planned_entry):
            return
        fill = adverse_fill(market_price, trade.direction, True, run.slippage_bps)
        trade.actual_entry = fill
        trade.entry_time = _event_datetime(event_time_ms)
        trade.status = "open"
        fee = _charge_fee(fill * float(trade.quantity), run.commission_pct)
        trade.fees_paid = float(trade.fees_paid) + fee
        trade.realized_pnl = float(trade.realized_pnl) - fee
        run.fees_paid = float(run.fees_paid) + fee
        run.realized_pnl = float(run.realized_pnl) - fee
        _add_event(db, trade, "ENTRY_FILLED", market_price, event_time_ms,
                   fill, float(trade.quantity), -fee, fee,
                   {"planned_entry": trade.planned_entry, "slippage_bps": run.slippage_bps})
        # Do not evaluate exits on the same tick that opened the position.
        return

    if trade.status not in ("open", "tp1_hit", "tp2_hit"):
        return
    stop_hit, _ = exit_triggered(trade.direction, market_price, trade.stop_loss, trade.tp1)
    if stop_hit:
        qty = float(trade.remaining_quantity)
        _record_exit(db, run, trade, market_price, event_time_ms, qty, "STOP_FILLED",
                     {"stop_loss": trade.stop_loss, "conservative_gap_handling": True})
        trade.status = "stopped"
        trade.closed_at = _event_datetime(event_time_ms)
        return

    targets = [
        ("open", "tp1_hit", float(trade.tp1), "TP1_FILLED"),
        ("tp1_hit", "tp2_hit", float(trade.tp2), "TP2_FILLED"),
        ("tp2_hit", "tp3_hit", float(trade.tp3), "TP3_FILLED"),
    ]
    for expected_status, next_status, target, event_type in targets:
        if trade.status != expected_status:
            continue
        _, hit = exit_triggered(trade.direction, market_price, trade.stop_loss, target)
        if not hit:
            break
        if next_status == "tp3_hit":
            qty = float(trade.remaining_quantity)
        else:
            qty = min(float(trade.remaining_quantity), float(trade.quantity) / 3.0)
        if qty <= 0:
            break
        _record_exit(db, run, trade, market_price, event_time_ms, qty, event_type,
                     {"target": target, "target_name": next_status.upper()})
        trade.status = next_status
        if next_status == "tp3_hit":
            trade.remaining_quantity = 0.0
            trade.closed_at = _event_datetime(event_time_ms)
            break


def process_forward_tick(event: dict[str, Any]) -> int:
    """Discover eligible signals and advance paper trades for one accepted Binance tick."""
    symbol = str(event["symbol"]).strip().upper()
    price = float(event["price"])
    event_time_ms = int(event["event_time_ms"])
    event_id = str(event.get("event_id") or "") or None
    if not symbol or not math.isfinite(price) or price <= 0 or event_time_ms < 0:
        raise ValueError("Invalid market tick")
    db = get_session_factory()()
    touched = 0
    try:
        candidate_runs = db.scalars(select(ForwardTestRun).where(
            ForwardTestRun.status.in_(("active", "stopping"))
        )).all()
        for candidate in candidate_runs:
            if symbol not in (candidate.symbols or []):
                continue
            run = db.scalar(select(ForwardTestRun).where(
                ForwardTestRun.id == candidate.id
            ).with_for_update())
            if run is None or run.status not in ("active", "stopping"):
                continue
            portfolio = db.get(Portfolio, run.portfolio_id)
            if portfolio is None:
                continue
            if run.status == "active":
                visibility = or_(
                    Signal.visibility == "public",
                    and_(Signal.visibility == "private", Signal.user_id == run.user_id),
                )
                signal_stmt = select(Signal).where(
                    Signal.symbol == symbol,
                    Signal.status.in_(ACTIVE_SIGNAL_STATUSES),
                    Signal.quality_score >= run.min_quality_score,
                    visibility,
                )
                if not run.include_existing_signals:
                    signal_stmt = signal_stmt.where(Signal.created_at >= run.started_at)
                signals = db.scalars(signal_stmt.order_by(Signal.created_at.asc())).all()
                for signal in signals:
                    exists = db.scalar(select(ForwardTestTrade.id).where(
                        ForwardTestTrade.run_id == run.id,
                        ForwardTestTrade.signal_id == signal.id,
                    ))
                    if exists:
                        continue
                    direction = "long" if signal.direction == "bullish" else "short"
                    entry, stop = float(signal.entry), float(signal.stop_loss)
                    targets = [float(signal.tp1), float(signal.tp2), float(signal.tp3)]
                    valid = (
                        stop < entry < targets[0] < targets[1] < targets[2]
                        if direction == "long"
                        else stop > entry > targets[0] > targets[1] > targets[2]
                    )
                    if not valid:
                        continue
                    # Do not create a paper fill from a tick that has already
                    # crossed the invalidation level before entry was observed.
                    if (direction == "long" and price <= stop) or (direction == "short" and price >= stop):
                        continue
                    active_trades = db.scalars(select(ForwardTestTrade).where(
                        ForwardTestTrade.run_id == run.id,
                        ForwardTestTrade.status.in_(ACTIVE_TRADE_STATUSES),
                    )).all()
                    if len(active_trades) >= int(portfolio.max_open_trades):
                        break
                    equity = max(0.0, float(run.initial_equity) + float(run.realized_pnl))
                    risk_cash = equity * float(run.risk_per_trade_pct) / 100.0
                    total_risk = sum(float(t.risk_cash) for t in active_trades)
                    max_total_risk = equity * float(portfolio.max_portfolio_risk_pct) / 100.0
                    if equity <= 0 or risk_cash <= 0 or total_risk + risk_cash > max_total_risk:
                        continue
                    quantity = risk_cash / abs(entry - stop)
                    trade = ForwardTestTrade(
                        id=str(uuid.uuid4()), run_id=run.id, user_id=run.user_id,
                        portfolio_id=run.portfolio_id, signal_id=signal.id,
                        symbol=symbol, direction=direction, status="pending_entry",
                        quality_score=int(signal.quality_score or 0),
                        planned_entry=entry, stop_loss=stop,
                        tp1=targets[0], tp2=targets[1], tp3=targets[2],
                        quantity=quantity, remaining_quantity=quantity,
                        risk_cash=risk_cash, realized_pnl=0.0, fees_paid=0.0,
                        last_event_time_ms=0, created_at=_now(),
                    )
                    db.add(trade)
                    db.flush()
                    _add_event(db, trade, "SIGNAL_IMPORTED", price, event_time_ms,
                               details={"signal_status": signal.status,
                                        "quality_score": signal.quality_score})
                    touched += 1
            trades = db.scalars(select(ForwardTestTrade).where(
                ForwardTestTrade.run_id == run.id,
                ForwardTestTrade.symbol == symbol,
                ForwardTestTrade.status.in_(ACTIVE_TRADE_STATUSES),
            ).with_for_update()).all()
            for trade in trades:
                before = (trade.status, trade.last_event_time_ms, trade.realized_pnl)
                _process_trade_tick(db, run, trade, price, event_time_ms, event_id)
                after = (trade.status, trade.last_event_time_ms, trade.realized_pnl)
                if before != after:
                    touched += 1
            if run.status == "stopping":
                remaining = db.scalar(select(func.count()).select_from(ForwardTestTrade).where(
                    ForwardTestTrade.run_id == run.id,
                    ForwardTestTrade.status.in_(ACTIVE_TRADE_STATUSES),
                )) or 0
                if not remaining:
                    run.status = "stopped"
                    run.stopped_at = _event_datetime(event_time_ms)
        db.commit()
        return touched
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
