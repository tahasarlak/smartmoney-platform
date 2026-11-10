"""Persistent, broker-independent Forex paper trading driven by confirmed price ticks."""
from __future__ import annotations
import math
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select, func
from sqlalchemy.dialects.postgresql import insert as pg_insert

from .database import get_session_factory
from .db_models import Portfolio
from .forex_models import ForexCandle, ForexPaperRun, ForexPaperTrade, ForexPaperEvent, ForexWorkerState
from .forex_intraday import SYMBOLS, PROVIDER

TIMEFRAME_SECONDS = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600, "4h": 14400}
ACTIVE_RUN_STATES = ("active", "stopping")
ACTIVE_TRADE_STATES = ("pending_entry", "open", "tp1_hit", "tp2_hit")
QUOTE_CURRENCY = {
    "EURUSD": "USD", "GBPUSD": "USD", "USDJPY": "JPY", "USDCHF": "CHF",
    "AUDUSD": "USD", "USDCAD": "CAD", "NZDUSD": "USD", "XAUUSD": "USD",
}
_latest_prices: dict[str, float] = {}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def quote_to_usd(symbol: str, prices: dict[str, float] | None = None) -> float:
    prices = prices or _latest_prices
    quote = QUOTE_CURRENCY[symbol]
    if quote == "USD":
        return 1.0
    conversion_symbol = {"JPY": "USDJPY", "CHF": "USDCHF", "CAD": "USDCAD"}[quote]
    rate = float(prices.get(conversion_symbol, 0))
    if not math.isfinite(rate) or rate <= 0:
        raise ValueError(f"Missing valid USD{quote} conversion price")
    return 1.0 / rate



def record_forex_worker_state(worker_id: str, *, status: str,
                              subscribed_symbols: list[str] | None = None,
                              last_tick_at: datetime | None = None,
                              last_error: str | None = None) -> None:
    from .database import session_scope
    stmt = pg_insert(ForexWorkerState).values(
        id=1, worker_id=worker_id, status=status,
        subscribed_symbols=subscribed_symbols or [],
        last_tick_at=last_tick_at, heartbeat_at=utcnow(),
        last_error=(last_error or None),
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=[ForexWorkerState.id],
        set_={"worker_id": stmt.excluded.worker_id, "status": stmt.excluded.status,
              "subscribed_symbols": stmt.excluded.subscribed_symbols,
              "last_tick_at": stmt.excluded.last_tick_at,
              "heartbeat_at": stmt.excluded.heartbeat_at,
              "last_error": stmt.excluded.last_error},
    )
    with session_scope() as db:
        db.execute(stmt)


def forex_worker_state() -> dict[str, Any]:
    db = get_session_factory()()
    try:
        row = db.get(ForexWorkerState, 1)
        if row is None:
            return {"status": "not_seen", "subscribed_symbols": [], "ready": False}
        age = (utcnow() - row.heartbeat_at).total_seconds()
        return {
            "status": row.status, "worker_id": row.worker_id,
            "subscribed_symbols": row.subscribed_symbols,
            "heartbeat_at": row.heartbeat_at.isoformat(),
            "last_tick_at": row.last_tick_at.isoformat() if row.last_tick_at else None,
            "last_error": row.last_error, "heartbeat_age_seconds": max(0, age),
            "ready": row.status == "ready" and age <= 120
                    and set(row.subscribed_symbols or []) == set(SYMBOLS),
        }
    finally:
        db.close()

def _event(db, trade, kind: str, market: float, ts: int, fill: float | None = None,
           qty: float = 0.0, pnl: float = 0.0, fee: float = 0.0, details: dict | None = None):
    db.add(ForexPaperEvent(
        id=str(uuid.uuid4()), trade_id=trade.id, event_type=kind,
        market_price=market, fill_price=fill, quantity=qty,
        pnl_usd=pnl, fee_usd=fee, event_time_ms=ts, details_json=details or {},
    ))


def _adverse_fill(price: float, direction: str, is_entry: bool, spread_bps: float, slippage_bps: float) -> float:
    # price stream is mid/last, not a guaranteed executable bid/ask quote.
    half_cost = (spread_bps / 2.0 + slippage_bps) / 10_000.0
    buy = (direction == "bullish") == is_entry
    return price * (1.0 + half_cost if buy else 1.0 - half_cost)


def _save_candle(db, candle: dict[str, Any]) -> None:
    stmt = pg_insert(ForexCandle).values(
        symbol=candle["symbol"], timeframe=candle["timeframe"], candle_time=int(candle["time"]),
        open=float(candle["open"]), high=float(candle["high"]), low=float(candle["low"]),
        close=float(candle["close"]), volume=float(candle.get("volume", 0.0)),
        provider=str(candle.get("provider", PROVIDER)),
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=[ForexCandle.symbol, ForexCandle.timeframe, ForexCandle.candle_time],
        set_={"open": stmt.excluded.open, "high": stmt.excluded.high,
              "low": stmt.excluded.low, "close": stmt.excluded.close,
              "volume": stmt.excluded.volume, "provider": stmt.excluded.provider},
    )
    db.execute(stmt)


def _candles_for_symbol(db, symbol: str, limit: int = 3000) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {}
    for tf in TIMEFRAME_SECONDS:
        rows = db.scalars(
            select(ForexCandle).where(
                ForexCandle.symbol == symbol, ForexCandle.timeframe == tf
            ).order_by(ForexCandle.candle_time.desc()).limit(limit)
        ).all()
        result[tf] = [
            {"time": r.candle_time, "open": r.open, "high": r.high,
             "low": r.low, "close": r.close, "volume": r.volume}
            for r in reversed(rows)
        ]
    return result


def _generate_latest_signals(db, symbol: str, closed_5m: dict[str, Any],
                             min_quality_score: int, min_rr: float,
                             risk_per_trade_pct: float) -> list[dict[str, Any]]:
    """Run the existing SMC scanner once for the latest fully closed decision bar."""
    from .historical_signal_engine import _analysis_window, _closed_as_of
    from .market_regime import analyze_market_regime
    from .market_regime_intelligence import analyze_market_regime_intelligence
    from .scanner import scan_symbol, TIMEFRAMES
    from .smc import analyze_smc
    from .v8_engine import _make_plan

    data = _candles_for_symbol(db, symbol)
    decision_time = int(closed_5m["time"]) + 300
    closed = {
        tf: _closed_as_of(data[tf], tf, decision_time)
        for tf in TIMEFRAME_SECONDS
    }
    if any(len(closed[tf]) < 50 for tf in TIMEFRAME_SECONDS):
        return []
    bounded = {tf: closed[tf][-500:] for tf in TIMEFRAME_SECONDS}
    windows = {tf: _analysis_window(bounded[tf]) for tf in TIMEFRAME_SECONDS}
    analyses = {
        tf: analyze_smc(symbol, windows[tf], swing_length=3)
        for tf in TIMEFRAMES
    }
    regimes = {
        tf: analyze_market_regime(windows[tf], tf)
        for tf in TIMEFRAMES
    }
    aggregate = analyze_market_regime_intelligence({
        tf: windows[tf] for tf in ("4h", "1h", "15m", "5m")
    })
    scan = scan_symbol(
        symbol, windows, analyses,
        settings={
            "min_quality_score": min_quality_score,
            "min_rr": min_rr,
            "allow_counter_trend": False,
        },
        regimes=regimes,
    )
    candidates = [
        item for item in scan.get("scenarios", [])
        if item.get("confirmation") == "confirmed_trigger"
        and int(item.get("quality_score", 0)) >= min_quality_score
        and isinstance(item.get("zone"), dict)
    ]
    output: list[dict[str, Any]] = []
    seen: set[str] = set()
    for scenario in candidates:
        direction = str(scenario.get("direction", ""))
        zone = scenario["zone"]
        zone_key = "|".join((direction, str(zone.get("formed_at")), str(zone.get("type"))))
        if direction not in ("bullish", "bearish") or zone_key in seen:
            continue
        plan = _make_plan(symbol, scenario, windows, min_rr, risk_per_trade_pct)
        if not plan or not plan.get("rr_filter_passed"):
            continue
        raw_targets = plan.get("take_profits") or []
        if len(raw_targets) < 2:
            continue
        targets = [float(item["price"]) for item in raw_targets[:3]]
        fractions = [0.50, 0.30, 0.20] if len(targets) >= 3 else [0.50, 0.50]
        levels = [{"price": price, "fraction": fraction}
                  for price, fraction in zip(targets, fractions)]
        output.append({
            "symbol": symbol, "direction": direction,
            "entry_reference": float(plan["entry"]),
            "stop_loss": float(plan["stop_loss"]),
            "take_profits": levels,
            "quality_score": int(scenario["quality_score"]),
            "signal_time": decision_time,
            "zone_key": zone_key,
            "market_regime": {
                "aggregate_regime": aggregate["aggregate_regime"],
                "dominant_direction": aggregate["dominant_direction"],
                "volatility_state": aggregate["volatility_state"],
            },
            "methodology_version": "historical-smc-1.0",
            "execution_allowed": False,
        })
        seen.add(zone_key)
    return output


def _try_create_signals(db, symbol: str, closed_5m: dict[str, Any]) -> int:
    created = 0
    prices = dict(_latest_prices)
    for run in db.scalars(select(ForexPaperRun).where(ForexPaperRun.status == "active")).all():
        if symbol not in (run.symbols or []) or utcnow() >= run.ends_at:
            continue
        portfolio = db.get(Portfolio, run.portfolio_id)
        if portfolio is None:
            continue
        try:
            conversion = quote_to_usd(symbol, prices)
            candidates = _generate_latest_signals(
                db, symbol, closed_5m, int(run.min_quality_score),
                float(run.min_rr), float(run.risk_per_trade_pct),
            )
        except (ValueError, RuntimeError, KeyError):
            continue
        for signal in candidates:
            exists = db.scalar(select(ForexPaperTrade.id).where(
                ForexPaperTrade.run_id == run.id,
                ForexPaperTrade.symbol == symbol,
                ForexPaperTrade.signal_time == int(signal["signal_time"]),
                ForexPaperTrade.direction == str(signal["direction"]),
            ))
            zone_exists = db.scalar(select(ForexPaperTrade.id).where(
                ForexPaperTrade.run_id == run.id,
                ForexPaperTrade.symbol == symbol,
                ForexPaperTrade.zone_key == str(signal["zone_key"]),
            ))
            if exists or zone_exists:
                continue
            direction = str(signal["direction"])
            entry = float(signal["entry_reference"])
            stop = float(signal["stop_loss"])
            distance = entry - stop if direction == "bullish" else stop - entry
            targets = signal.get("take_profits") or []
            if distance <= 0 or len(targets) < 1:
                continue
            if not all(math.isfinite(float(x["price"])) for x in targets):
                continue
            equity = max(0.0, float(run.initial_equity) + float(run.realized_pnl_usd))
            risk_cash = equity * float(run.risk_per_trade_pct) / 100.0
            active = db.scalars(select(ForexPaperTrade).where(
                ForexPaperTrade.run_id == run.id,
                ForexPaperTrade.status.in_(ACTIVE_TRADE_STATES),
            ).with_for_update()).all()
            if len(active) >= int(portfolio.max_open_trades):
                continue
            committed = sum(float(t.risk_cash_usd) for t in active)
            cap = equity * float(portfolio.max_portfolio_risk_pct) / 100.0
            if equity <= 0 or risk_cash <= 0 or committed + risk_cash > cap:
                continue
            quantity = risk_cash / (distance * conversion)
            trade = ForexPaperTrade(
                id=str(uuid.uuid4()), run_id=run.id, user_id=run.user_id,
                portfolio_id=run.portfolio_id, symbol=symbol, direction=direction,
                status="pending_entry", signal_time=int(signal["signal_time"]),
                zone_key=str(signal["zone_key"])[:240],
                quality_score=int(signal.get("quality_score", 0)),
                planned_entry=entry, stop_loss=stop, initial_stop_loss=stop,
                take_profits=targets, next_target_index=0, quantity=quantity,
                remaining_quantity=quantity, risk_cash_usd=risk_cash,
                realized_pnl_usd=0.0, fees_usd=0.0, last_event_time_ms=0,
            )
            db.add(trade)
            db.flush()
            _event(db, trade, "SIGNAL_CREATED", prices.get(symbol, entry),
                   int(signal["signal_time"] * 1000), details={
                       "methodology": signal.get("methodology_version"),
                       "market_regime": signal.get("market_regime"),
                       "zone_key": signal.get("zone_key"),
                       "execution_allowed": False,
                   })
            created += 1
    return created


def _close_quantity(db, run, trade, market_price: float, ts: int, qty: float,
                    event_type: str, conversion: float, details: dict | None = None) -> None:
    qty = min(float(qty), float(trade.remaining_quantity))
    if qty <= 1e-12:
        return
    fill = _adverse_fill(market_price, trade.direction, False,
                         float(run.spread_bps), float(run.slippage_bps))
    side = 1.0 if trade.direction == "bullish" else -1.0
    gross = (fill - float(trade.actual_entry)) * qty * side * conversion
    fee = abs(fill * qty) * conversion * float(run.commission_pct) / 100.0
    net = gross - fee
    trade.realized_pnl_usd = float(trade.realized_pnl_usd) + net
    trade.fees_usd = float(trade.fees_usd) + fee
    trade.remaining_quantity = max(0.0, float(trade.remaining_quantity) - qty)
    run.realized_pnl_usd = float(run.realized_pnl_usd) + net
    run.fees_usd = float(run.fees_usd) + fee
    _event(db, trade, event_type, market_price, ts, fill, qty, net, fee, details)


def _advance_trade(db, run, trade, price: float, ts: int, conversion: float) -> None:
    if ts <= int(trade.last_event_time_ms or 0):
        return
    trade.last_event_time_ms = ts
    if trade.status == "pending_entry":
        triggered = price <= trade.planned_entry if trade.direction == "bullish" else price >= trade.planned_entry
        invalidated = price <= trade.stop_loss if trade.direction == "bullish" else price >= trade.stop_loss
        if invalidated:
            trade.status = "cancelled"
            _event(db, trade, "ENTRY_CANCELLED_INVALIDATED", price, ts)
            return
        if not triggered:
            return
        fill = _adverse_fill(price, trade.direction, True, run.spread_bps, run.slippage_bps)
        trade.actual_entry = fill
        trade.status = "open"
        trade.entry_time = datetime.fromtimestamp(ts / 1000, tz=timezone.utc)
        fee = abs(fill * float(trade.quantity)) * conversion * float(run.commission_pct) / 100.0
        trade.fees_usd = float(trade.fees_usd) + fee
        trade.realized_pnl_usd = float(trade.realized_pnl_usd) - fee
        run.fees_usd = float(run.fees_usd) + fee
        run.realized_pnl_usd = float(run.realized_pnl_usd) - fee
        _event(db, trade, "ENTRY_FILLED", price, ts, fill, trade.quantity, -fee, fee)
        return

    if trade.status not in ("open", "tp1_hit", "tp2_hit"):
        return
    long = trade.direction == "bullish"
    stop_hit = price <= trade.stop_loss if long else price >= trade.stop_loss
    if stop_hit:
        _close_quantity(db, run, trade, price, ts, trade.remaining_quantity,
                        "STOP_FILLED", conversion, {"stop": trade.stop_loss})
        trade.status = "stopped"
        trade.closed_at = datetime.fromtimestamp(ts / 1000, tz=timezone.utc)
        return

    targets = trade.take_profits or []
    while int(trade.next_target_index) < len(targets):
        idx = int(trade.next_target_index)
        target = float(targets[idx]["price"])
        hit = price >= target if long else price <= target
        if not hit:
            break
        fraction = float(targets[idx]["fraction"])
        qty = float(trade.quantity) * fraction
        _close_quantity(db, run, trade, target, ts, qty, f"TP{idx + 1}_FILLED",
                        conversion, {"target": target, "fraction": fraction})
        trade.next_target_index = idx + 1
        if idx == 0:
            trade.stop_loss = float(trade.actual_entry)
        if trade.remaining_quantity <= 1e-10:
            trade.status = "closed"
            trade.closed_at = datetime.fromtimestamp(ts / 1000, tz=timezone.utc)
            break
        trade.status = f"tp{idx + 1}_hit"


def process_forex_tick(tick: dict[str, Any], closed_candles: list[dict[str, Any]] | None = None) -> dict[str, int]:
    symbol = str(tick["symbol"]).upper()
    price = float(tick["price"])
    ts = int(tick["event_time_ms"])
    if symbol not in SYMBOLS or not math.isfinite(price) or price <= 0 or ts <= 0:
        raise ValueError("Invalid Forex tick")
    _latest_prices[symbol] = price
    try:
        record_forex_worker_state(
            os.getenv("TRADF_FOREX_WORKER_ID", "forex-worker"),
            status="ready", subscribed_symbols=list(SYMBOLS),
            last_tick_at=datetime.fromtimestamp(ts / 1000, tz=timezone.utc),
        )
    except Exception:
        # The main candle/trade transaction below remains authoritative.
        pass
    db = get_session_factory()()
    touched = 0
    try:
        for candle in closed_candles or []:
            _save_candle(db, candle)
        runs = db.scalars(select(ForexPaperRun).where(
            ForexPaperRun.status.in_(ACTIVE_RUN_STATES)
        ).with_for_update()).all()
        for run in runs:
            if utcnow() >= run.ends_at and run.status == "active":
                run.status = "stopping"
            if symbol not in (run.symbols or []):
                continue
            run.last_tick_at = datetime.fromtimestamp(ts / 1000, tz=timezone.utc)
            trades = db.scalars(select(ForexPaperTrade).where(
                ForexPaperTrade.run_id == run.id,
                ForexPaperTrade.symbol == symbol,
                ForexPaperTrade.status.in_(ACTIVE_TRADE_STATES),
            ).with_for_update()).all()
            try:
                conversion = quote_to_usd(symbol)
            except ValueError:
                continue
            for trade in trades:
                before = (trade.status, trade.last_event_time_ms, trade.remaining_quantity)
                _advance_trade(db, run, trade, price, ts, conversion)
                if before != (trade.status, trade.last_event_time_ms, trade.remaining_quantity):
                    touched += 1
            if run.status == "stopping":
                # At the 21-day boundary, cancel unfilled entries and mark open
                # positions to market with a final conservative paper close.
                for trade in trades:
                    if trade.status == "pending_entry":
                        trade.status = "cancelled"
                    elif trade.status in ("open", "tp1_hit", "tp2_hit"):
                        _close_quantity(db, run, trade, price, ts, trade.remaining_quantity,
                                        "TIME_EXIT", conversion, {"reason": "paper_period_ended"})
                        trade.status = "closed"
                        trade.closed_at = datetime.fromtimestamp(ts / 1000, tz=timezone.utc)
                remaining = db.scalar(select(func.count()).select_from(ForexPaperTrade).where(
                    ForexPaperTrade.run_id == run.id,
                    ForexPaperTrade.status.in_(ACTIVE_TRADE_STATES),
                )) or 0
                if remaining == 0:
                    run.status = "completed"
                    run.stopped_at = datetime.fromtimestamp(ts / 1000, tz=timezone.utc)
        # New signals are only evaluated after a real 5m candle has closed.
        for candle in closed_candles or []:
            if candle.get("timeframe") == "5m":
                touched += _try_create_signals(db, symbol, candle)
        db.commit()
        return {"trades_touched": touched, "candles_saved": len(closed_candles or [])}
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def start_forex_paper_run(user_id: str, portfolio_id: str, *, risk_per_trade_pct: float = 0.25,
                          min_quality_score: int = 65, min_rr: float = 2.0,
                          commission_pct: float = 0.0, spread_bps: float = 1.5,
                          slippage_bps: float = 0.5, confirm_paper_only: bool = False) -> dict[str, Any]:
    if confirm_paper_only is not True:
        raise ValueError("Explicit confirm_paper_only=true is required")
    if not os.getenv("TWELVE_DATA_API_KEY", "").strip():
        raise ValueError("TWELVE_DATA_API_KEY is not configured")
    worker = forex_worker_state()
    if not worker.get("ready"):
        raise ValueError("Forex worker is not ready; confirm all eight Twelve Data subscriptions and a fresh worker heartbeat first")
    if not 0 < risk_per_trade_pct <= 2 or not 0 <= min_quality_score <= 100:
        raise ValueError("Invalid risk or quality settings")
    if not 0.5 <= min_rr <= 10 or not 0 <= commission_pct <= 1:
        raise ValueError("Invalid RR or commission setting")
    if not 0 <= spread_bps <= 500 or not 0 <= slippage_bps <= 500:
        raise ValueError("Invalid spread/slippage setting")
    db = get_session_factory()()
    try:
        portfolio = db.scalar(select(Portfolio).where(
            Portfolio.id == portfolio_id, Portfolio.user_id == user_id
        ).with_for_update())
        if portfolio is None:
            raise LookupError("Portfolio not found")
        if risk_per_trade_pct > float(portfolio.max_trade_risk_pct):
            raise ValueError("Per-trade risk exceeds portfolio max_trade_risk_pct")
        active = db.scalar(select(ForexPaperRun.id).where(
            ForexPaperRun.user_id == user_id, ForexPaperRun.portfolio_id == portfolio_id,
            ForexPaperRun.status.in_(ACTIVE_RUN_STATES),
        ).limit(1))
        if active:
            raise ValueError("An active Forex paper run already exists for this portfolio")
        for symbol in SYMBOLS:
            counts = {}
            for tf in TIMEFRAME_SECONDS:
                counts[tf] = db.scalar(select(func.count()).select_from(ForexCandle).where(
                    ForexCandle.symbol == symbol, ForexCandle.timeframe == tf
                )) or 0
            if any(count < 50 for count in counts.values()):
                raise ValueError(f"{symbol} needs at least 50 imported candles per timeframe; found {counts}")
        now = utcnow()
        row = ForexPaperRun(
            id=str(uuid.uuid4()), user_id=user_id, portfolio_id=portfolio_id,
            status="active", symbols=list(SYMBOLS), initial_equity=float(portfolio.initial_equity),
            risk_per_trade_pct=float(risk_per_trade_pct), min_quality_score=int(min_quality_score),
            min_rr=float(min_rr), commission_pct=float(commission_pct),
            spread_bps=float(spread_bps), slippage_bps=float(slippage_bps),
            realized_pnl_usd=0.0, fees_usd=0.0, started_at=now,
            ends_at=now + timedelta(days=21),
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return {"id": row.id, "status": row.status, "symbols": row.symbols,
                "started_at": row.started_at.isoformat(), "ends_at": row.ends_at.isoformat(),
                "duration_days": 21, "mode": "paper", "execution_allowed": False}
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def forex_paper_status(user_id: str, portfolio_id: str) -> dict[str, Any]:
    db = get_session_factory()()
    try:
        run = db.scalar(select(ForexPaperRun).where(
            ForexPaperRun.user_id == user_id, ForexPaperRun.portfolio_id == portfolio_id
        ).order_by(ForexPaperRun.created_at.desc()).limit(1))
        if run is None:
            return {"status": "not_configured", "mode": "paper", "execution_allowed": False}
        total_trades = db.scalar(select(func.count()).select_from(ForexPaperTrade).where(
            ForexPaperTrade.run_id == run.id
        )) or 0
        closed_count = db.scalar(select(func.count()).select_from(ForexPaperTrade).where(
            ForexPaperTrade.run_id == run.id,
            ForexPaperTrade.status.in_(("closed", "stopped"))
        )) or 0
        wins = db.scalar(select(func.count()).select_from(ForexPaperTrade).where(
            ForexPaperTrade.run_id == run.id,
            ForexPaperTrade.status.in_(("closed", "stopped")),
            ForexPaperTrade.realized_pnl_usd > 0
        )) or 0
        trades = db.scalars(select(ForexPaperTrade).where(
            ForexPaperTrade.run_id == run.id
        ).order_by(ForexPaperTrade.created_at.desc()).limit(100)).all()
        wins = sum(1 for t in closed if float(t.realized_pnl_usd) > 0)
        return {
            "status": run.status, "run_id": run.id, "symbols": run.symbols,
            "started_at": run.started_at.isoformat(), "ends_at": run.ends_at.isoformat(),
            "initial_equity_usd": run.initial_equity,
            "realized_pnl_usd": run.realized_pnl_usd, "fees_usd": run.fees_usd,
            "equity_usd": run.initial_equity + run.realized_pnl_usd,
            "trade_count": int(total_trades), "closed_trade_count": int(closed_count),
            "win_rate_pct": (wins / closed_count * 100.0) if closed_count else None,
            "recent_trades": [{
                "symbol": t.symbol, "direction": t.direction, "status": t.status,
                "quality_score": t.quality_score, "entry": t.actual_entry or t.planned_entry,
                "stop_loss": t.stop_loss, "realized_pnl_usd": t.realized_pnl_usd,
                "fees_usd": t.fees_usd, "created_at": t.created_at.isoformat(),
            } for t in trades],
            "mode": "paper", "live_execution_enabled": False, "execution_allowed": False,
            "warning": "Paper results are simulated and do not establish future profitability.",
        }
    finally:
        db.close()


def stop_forex_paper_run(user_id: str, run_id: str) -> dict[str, Any]:
    db = get_session_factory()()
    try:
        run = db.scalar(select(ForexPaperRun).where(
            ForexPaperRun.id == run_id, ForexPaperRun.user_id == user_id
        ).with_for_update())
        if run is None:
            raise LookupError("Forex paper run not found")
        if run.status == "active":
            run.status = "stopping"
        db.commit()
        return {"run_id": run.id, "status": run.status,
                "note": "No new entries will be created; open paper positions will be settled by the worker.",
                "execution_allowed": False}
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
