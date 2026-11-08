from __future__ import annotations

import hashlib
import hmac
import json
import math
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select, delete, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as OrmSession

from .database import get_session_factory
from .db_models import (
    User, Session as LoginSession, Portfolio, BrokerAccount,
    PaperOrder, AuditEvent, BacktestRun, ForwardTestRun, ForwardTestTrade,
    ExecutionTrade, ExecutionEvent,
)
from .risk_engine import (
    calculate_risk_position_size, calculate_correlation_matrix,
    assess_portfolio_risk, allocate_capital, allocate_capital_with_correlation,
)
from .execution_engine import (
    validate_execution_plan, process_trade_tick, cancel_pending_trade,
)
from .forward_testing import (
    start_forward_run, stop_forward_run, list_forward_runs,
    list_forward_trades, list_forward_events, forward_summary,
    compare_forward_to_backtest,
)

TOKEN_TTL_HOURS = 12
PBKDF2_ITERATIONS = 310_000


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None = None) -> str:
    value = value or _now()
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


def _dt(value: datetime | str) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _session():
    """Open a short-lived SQLAlchemy session; each caller owns its transaction."""
    return get_session_factory()()


def init_v11_db() -> None:
    """
    Compatibility shim for the existing main.py import/call.
    Schema creation is intentionally owned by Alembic, never by application startup.
    """
    return None


def _hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt.hex()}${digest.hex()}"


def _verify_password(password: str, encoded: str) -> bool:
    try:
        scheme, rounds, salt_hex, digest_hex = encoded.split("$", 3)
        if scheme != "pbkdf2_sha256":
            return False
        actual = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), bytes.fromhex(salt_hex), int(rounds)
        ).hex()
        return hmac.compare_digest(actual, digest_hex)
    except (ValueError, TypeError):
        return False


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def register_user(email: str, password: str) -> dict[str, Any]:
    email = email.strip().lower()
    if len(password) < 10:
        raise ValueError("Password must contain at least 10 characters")

    user_id, portfolio_id = str(uuid.uuid4()), str(uuid.uuid4())
    now = _now()
    db = _session()
    try:
        user = User(
            id=user_id, email=email, password_hash=_hash_password(password),
            is_active=True, created_at=now,
        )
        portfolio = Portfolio(
            id=portfolio_id, user_id=user_id, name="Main Portfolio",
            base_currency="USDT", initial_equity=10_000.0,
            max_open_trades=3, max_portfolio_risk_pct=3.0,
            max_trade_risk_pct=1.0, created_at=now,
        )
        # Flush the parent row before the portfolio so PostgreSQL can
        # satisfy the portfolio.user_id foreign key deterministically.
        db.add(user)
        db.flush()
        db.add(portfolio)
        db.flush()
        _audit(db, user_id, "USER_REGISTERED", portfolio_id, None, {})
        db.commit()
        return {
            "id": user_id, "email": email, "created_at": _iso(now),
            "default_portfolio_id": portfolio_id,
        }
    except IntegrityError as exc:
        db.rollback()
        raise ValueError("An account with this email already exists") from exc
    finally:
        db.close()


def create_session(email: str, password: str) -> dict[str, Any]:
    db = _session()
    try:
        user = db.scalar(select(User).where(func.lower(User.email) == email.strip().lower()))
        if user is None or not user.is_active or not _verify_password(password, user.password_hash):
            raise ValueError("Invalid email or password")

        token = secrets.token_urlsafe(40)
        expires = _now() + timedelta(hours=TOKEN_TTL_HOURS)
        db.add(LoginSession(
            token_hash=_token_hash(token), user_id=user.id,
            expires_at=expires, created_at=_now(),
        ))
        db.commit()
        return {
            "access_token": token, "token_type": "bearer",
            "expires_at": _iso(expires),
            "user": {"id": user.id, "email": user.email},
        }
    finally:
        db.close()


def revoke_session(token: str | None) -> None:
    if not token:
        return
    db = _session()
    try:
        db.execute(delete(LoginSession).where(LoginSession.token_hash == _token_hash(token)))
        db.commit()
    finally:
        db.close()


def authenticate_token(token: str | None) -> dict[str, str]:
    if not token:
        raise HTTPException(status_code=401, detail="Bearer token required")
    db = _session()
    try:
        row = db.execute(
            select(User.id, User.email, LoginSession.expires_at)
            .join(LoginSession, LoginSession.user_id == User.id)
            .where(
                LoginSession.token_hash == _token_hash(token),
                User.is_active.is_(True),
            )
        ).first()
        if row is None or _dt(row.expires_at) <= _now():
            raise HTTPException(status_code=401, detail="Session is invalid or expired")
        return {"id": row.id, "email": row.email}
    finally:
        db.close()


def _audit(
    db: OrmSession, user_id: str, event_type: str,
    portfolio_id: str | None = None, entity_id: str | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    db.add(AuditEvent(
        user_id=user_id, portfolio_id=portfolio_id, event_type=event_type,
        entity_id=entity_id, details_json=details or {}, created_at=_now(),
    ))


def _owned_portfolio(db: OrmSession, user_id: str, portfolio_id: str) -> Portfolio:
    portfolio = db.scalar(select(Portfolio).where(
        Portfolio.id == portfolio_id, Portfolio.user_id == user_id
    ))
    if portfolio is None:
        raise LookupError("Portfolio not found")
    return portfolio


def _order_dict(order: PaperOrder) -> dict[str, Any]:
    return {
        "id": order.id, "user_id": order.user_id, "portfolio_id": order.portfolio_id,
        "account_id": order.account_id, "broker": order.broker, "symbol": order.symbol,
        "side": order.side, "quantity": order.quantity, "entry_price": order.entry_price,
        "stop_loss": order.stop_loss, "take_profit": order.take_profit,
        "risk_cash": order.risk_cash, "status": order.status,
        "exit_price": order.exit_price, "realized_pnl": order.realized_pnl,
        "created_at": _iso(order.created_at),
        "closed_at": _iso(order.closed_at) if order.closed_at else None,
    }


def _portfolio_dict(db: OrmSession, p: Portfolio) -> dict[str, Any]:
    accounts = db.scalars(select(BrokerAccount).where(
        BrokerAccount.portfolio_id == p.id,
        BrokerAccount.user_id == p.user_id,
    ).order_by(BrokerAccount.created_at)).all()
    orders = db.scalars(select(PaperOrder).where(
        PaperOrder.portfolio_id == p.id, PaperOrder.user_id == p.user_id
    )).all()
    realized = sum(float(o.realized_pnl or 0) for o in orders if o.status == "closed")
    open_orders = [o for o in orders if o.status == "open"]
    execution_trades = db.scalars(select(ExecutionTrade).where(
        ExecutionTrade.portfolio_id == p.id, ExecutionTrade.user_id == p.user_id,
    )).all()
    # Partial exits realize PnL before the remaining position is closed.
    # Include realized PnL from every execution state in portfolio cash equity.
    realized_execution = sum(float(t.realized_pnl or 0) - float(t.fees_paid or 0)
                             for t in execution_trades)
    active_execution = [t for t in execution_trades if t.status in ("pending_entry", "open", "partially_closed") and t.remaining_quantity > 0]
    realized += realized_execution
    open_risk = sum(float(o.risk_cash) for o in open_orders)
    for t in active_execution:
        entry = float(t.avg_entry_price or t.planned_entry)
        per_unit = (entry - float(t.stop_loss)) if t.side == "long" else (float(t.stop_loss) - entry)
        open_risk += max(0.0, per_unit * float(t.remaining_quantity))
    equity = float(p.initial_equity)
    return {
        "id": p.id, "name": p.name, "base_currency": p.base_currency,
        "initial_equity": equity, "realized_pnl": round(realized, 8),
        "cash_equity": round(equity + realized, 8),
        "open_positions": len(open_orders) + len(active_execution), "open_risk_cash": round(open_risk, 8),
        "open_risk_pct": round(open_risk / equity * 100, 6),
        "max_open_trades": p.max_open_trades,
        "max_portfolio_risk_pct": p.max_portfolio_risk_pct,
        "max_trade_risk_pct": p.max_trade_risk_pct,
        "accounts": [{
            "id": a.id, "broker": a.broker, "mode": a.mode,
            "label": a.label, "created_at": _iso(a.created_at),
        } for a in accounts],
        "created_at": _iso(p.created_at),
    }


def create_portfolio(
    user_id: str, name: str, initial_equity: float,
    max_open_trades: int = 3, max_portfolio_risk_pct: float = 3.0,
    max_trade_risk_pct: float = 1.0, base_currency: str = "USDT",
) -> dict[str, Any]:
    if not name.strip() or len(name) > 80:
        raise ValueError("Portfolio name must contain 1..80 characters")
    values = (initial_equity, max_portfolio_risk_pct, max_trade_risk_pct)
    if (not all(math.isfinite(v) for v in values) or initial_equity <= 0
            or not 0 <= max_portfolio_risk_pct <= 100
            or not 0 <= max_trade_risk_pct <= 100):
        raise ValueError("Invalid portfolio equity or risk limits")
    if not 1 <= max_open_trades <= 100:
        raise ValueError("max_open_trades must be between 1 and 100")

    pid, now = str(uuid.uuid4()), _now()
    db = _session()
    try:
        p = Portfolio(
            id=pid, user_id=user_id, name=name.strip(),
            base_currency=base_currency.upper(), initial_equity=initial_equity,
            max_open_trades=max_open_trades,
            max_portfolio_risk_pct=max_portfolio_risk_pct,
            max_trade_risk_pct=max_trade_risk_pct, created_at=now,
        )
        db.add(p)
        _audit(db, user_id, "PORTFOLIO_CREATED", pid, pid, {"name": name.strip()})
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
    return get_portfolio(user_id, pid)


def get_portfolio(user_id: str, portfolio_id: str) -> dict[str, Any]:
    db = _session()
    try:
        return _portfolio_dict(db, _owned_portfolio(db, user_id, portfolio_id))
    finally:
        db.close()


def list_portfolios(user_id: str) -> list[dict[str, Any]]:
    db = _session()
    try:
        rows = db.scalars(select(Portfolio).where(
            Portfolio.user_id == user_id
        ).order_by(Portfolio.created_at)).all()
        return [_portfolio_dict(db, p) for p in rows]
    finally:
        db.close()


def create_broker_account(user_id: str, portfolio_id: str, broker: str, label: str) -> dict[str, Any]:
    broker = broker.lower()
    if broker not in ("binance", "mt5"):
        raise ValueError("broker must be binance or mt5")
    if not label.strip() or len(label) > 80:
        raise ValueError("Account label must contain 1..80 characters")

    aid, now = str(uuid.uuid4()), _now()
    db = _session()
    try:
        _owned_portfolio(db, user_id, portfolio_id)
        account = BrokerAccount(
            id=aid, user_id=user_id, portfolio_id=portfolio_id,
            broker=broker, mode="paper", label=label.strip(), created_at=now,
        )
        db.add(account)
        _audit(db, user_id, "PAPER_ACCOUNT_CREATED", portfolio_id, aid,
               {"broker": broker, "mode": "paper"})
        db.commit()
        return {
            "id": aid, "portfolio_id": portfolio_id, "broker": broker,
            "mode": "paper", "label": label.strip(), "created_at": _iso(now),
        }
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def list_broker_accounts(user_id: str, portfolio_id: str) -> list[dict[str, Any]]:
    db = _session()
    try:
        _owned_portfolio(db, user_id, portfolio_id)
        rows = db.scalars(select(BrokerAccount).where(
            BrokerAccount.user_id == user_id,
            BrokerAccount.portfolio_id == portfolio_id,
        ).order_by(BrokerAccount.created_at)).all()
        return [{
            "id": r.id, "portfolio_id": r.portfolio_id, "broker": r.broker,
            "mode": r.mode, "label": r.label, "created_at": _iso(r.created_at),
        } for r in rows]
    finally:
        db.close()


def create_paper_order(
    user_id: str, account_id: str, symbol: str, side: str,
    quantity: float, reference_price: float, stop_loss: float, take_profit: float,
) -> dict[str, Any]:
    symbol, side = symbol.strip().upper(), side.lower()
    if not symbol or len(symbol) > 30 or not symbol.replace("_", "").isalnum():
        raise ValueError("Invalid symbol")
    if side not in ("long", "short"):
        raise ValueError("side must be long or short")
    vals = (quantity, reference_price, stop_loss, take_profit)
    if not all(math.isfinite(v) and v > 0 for v in vals):
        raise ValueError("Quantity and all prices must be finite and positive")
    if side == "long" and not stop_loss < reference_price < take_profit:
        raise ValueError("For long orders require stop_loss < reference_price < take_profit")
    if side == "short" and not take_profit < reference_price < stop_loss:
        raise ValueError("For short orders require take_profit < reference_price < stop_loss")

    oid, now = str(uuid.uuid4()), _now()
    db = _session()
    try:
        account = db.execute(
            select(BrokerAccount, Portfolio)
            .join(Portfolio, Portfolio.id == BrokerAccount.portfolio_id)
            .where(
                BrokerAccount.id == account_id,
                BrokerAccount.user_id == user_id,
                Portfolio.user_id == user_id,
            )
            # Serialize order admission per portfolio. Without this row lock,
            # concurrent requests can both pass the same risk/open-position checks.
            .with_for_update(of=Portfolio)
        ).first()
        if account is None:
            raise LookupError("Broker account not found")
        a, p = account
        open_orders = db.scalars(select(PaperOrder).where(
            PaperOrder.portfolio_id == p.id,
            PaperOrder.user_id == user_id,
            PaperOrder.status == "open",
        )).all()
        if len(open_orders) >= int(p.max_open_trades):
            raise ValueError("Portfolio max_open_trades limit reached")

        risk_cash = abs(reference_price - stop_loss) * quantity
        realized = db.scalar(select(func.coalesce(func.sum(PaperOrder.realized_pnl), 0)).where(
            PaperOrder.portfolio_id == p.id,
            PaperOrder.user_id == user_id,
            PaperOrder.status == "closed",
        )) or 0
        equity = float(p.initial_equity) + float(realized)
        if equity <= 0:
            raise ValueError("Portfolio equity is not positive")
        if risk_cash / equity * 100 > float(p.max_trade_risk_pct):
            raise ValueError("Per-trade risk limit exceeded")
        total_open_risk = sum(float(o.risk_cash) for o in open_orders)
        if (total_open_risk + risk_cash) / equity * 100 > float(p.max_portfolio_risk_pct):
            raise ValueError("Portfolio aggregate open-risk limit exceeded")

        order = PaperOrder(
            id=oid, user_id=user_id, portfolio_id=p.id, account_id=a.id,
            broker=a.broker, symbol=symbol, side=side, quantity=quantity,
            entry_price=reference_price, stop_loss=stop_loss,
            take_profit=take_profit, risk_cash=risk_cash, status="open",
            created_at=now,
        )
        db.add(order)
        _audit(db, user_id, "PAPER_ORDER_OPENED", p.id, oid, {
            "broker": a.broker, "symbol": symbol, "side": side,
            "quantity": quantity, "reference_price": reference_price,
        })
        db.commit()
        db.refresh(order)
        return _order_dict(order)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def get_order(user_id: str, order_id: str) -> dict[str, Any]:
    db = _session()
    try:
        order = db.scalar(select(PaperOrder).where(
            PaperOrder.id == order_id, PaperOrder.user_id == user_id
        ))
        if order is None:
            raise LookupError("Order not found")
        return _order_dict(order)
    finally:
        db.close()


def list_orders(user_id: str, portfolio_id: str, status: str | None = None) -> list[dict[str, Any]]:
    db = _session()
    try:
        _owned_portfolio(db, user_id, portfolio_id)
        stmt = select(PaperOrder).where(
            PaperOrder.user_id == user_id, PaperOrder.portfolio_id == portfolio_id
        )
        if status:
            stmt = stmt.where(PaperOrder.status == status.lower())
        rows = db.scalars(stmt.order_by(PaperOrder.created_at.desc())).all()
        return [_order_dict(o) for o in rows]
    finally:
        db.close()


def close_paper_order(user_id: str, order_id: str, exit_price: float) -> dict[str, Any]:
    if not math.isfinite(exit_price) or exit_price <= 0:
        raise ValueError("exit_price must be finite and positive")
    db = _session()
    try:
        order = db.scalar(select(PaperOrder).where(
            PaperOrder.id == order_id, PaperOrder.user_id == user_id
        ).with_for_update())
        if order is None:
            raise LookupError("Order not found")
        if order.status != "open":
            raise ValueError("Order is already closed")
        direction = 1 if order.side == "long" else -1
        pnl = (exit_price - float(order.entry_price)) * float(order.quantity) * direction
        order.status, order.exit_price, order.realized_pnl = "closed", exit_price, pnl
        order.closed_at = _now()
        _audit(db, user_id, "PAPER_ORDER_CLOSED", order.portfolio_id, order_id,
               {"exit_price": exit_price, "realized_pnl": pnl})
        db.commit()
        db.refresh(order)
        return _order_dict(order)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def save_backtest_run(user_id: str, portfolio_id: str, result: dict[str, Any]) -> dict[str, Any]:
    run_id, now = str(uuid.uuid4()), _now()
    # Reject NaN/Infinity before attempting to store JSON in PostgreSQL.
    json.dumps(result, separators=(",", ":"), allow_nan=False)
    db = _session()
    try:
        _owned_portfolio(db, user_id, portfolio_id)
        db.add(BacktestRun(
            id=run_id, user_id=user_id, portfolio_id=portfolio_id,
            result_json=result, created_at=now,
        ))
        _audit(db, user_id, "SHARED_BACKTEST_COMPLETED", portfolio_id, run_id, {
            "trade_count": result.get("trade_count"), "net_pnl": result.get("net_pnl"),
        })
        db.commit()
        return {"id": run_id, "portfolio_id": portfolio_id, "created_at": _iso(now), "result": result}
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def list_backtest_runs(user_id: str, portfolio_id: str, limit: int = 20) -> list[dict[str, Any]]:
    db = _session()
    try:
        _owned_portfolio(db, user_id, portfolio_id)
        rows = db.scalars(select(BacktestRun).where(
            BacktestRun.user_id == user_id,
            BacktestRun.portfolio_id == portfolio_id,
        ).order_by(BacktestRun.created_at.desc()).limit(limit)).all()
        return [{
            "id": r.id, "created_at": _iso(r.created_at), "result": r.result_json,
        } for r in rows]
    finally:
        db.close()


def list_audit_events(user_id: str, limit: int = 100) -> list[dict[str, Any]]:
    db = _session()
    try:
        rows = db.scalars(select(AuditEvent).where(
            AuditEvent.user_id == user_id
        ).order_by(AuditEvent.id.desc()).limit(limit)).all()
        return [{
            "id": r.id, "portfolio_id": r.portfolio_id, "event_type": r.event_type,
            "entity_id": r.entity_id, "details_json": r.details_json,
            "created_at": _iso(r.created_at), "details": r.details_json,
        } for r in rows]
    finally:
        db.close()


class RegisterRequest(BaseModel):
    email: str = Field(min_length=5, max_length=254)
    password: str = Field(min_length=10, max_length=128)

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        value = value.strip().lower()
        if "@" not in value or value.startswith("@") or value.endswith("@") or "." not in value.rsplit("@", 1)[-1]:
            raise ValueError("A valid email address is required")
        return value


class LoginRequest(BaseModel):
    email: str = Field(min_length=5, max_length=254)
    password: str = Field(min_length=1, max_length=128)

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        value = value.strip().lower()
        if "@" not in value or value.startswith("@") or value.endswith("@") or "." not in value.rsplit("@", 1)[-1]:
            raise ValueError("A valid email address is required")
        return value


class PortfolioRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    initial_equity: float = Field(gt=0)
    base_currency: str = Field(default="USDT", min_length=3, max_length=8)
    max_open_trades: int = Field(default=3, ge=1, le=100)
    max_portfolio_risk_pct: float = Field(default=3, ge=0, le=100)
    max_trade_risk_pct: float = Field(default=1, ge=0, le=100)


class BrokerAccountRequest(BaseModel):
    portfolio_id: str
    broker: str
    label: str = Field(min_length=1, max_length=80)

    @field_validator("broker")
    @classmethod
    def validate_broker(cls, value: str) -> str:
        if value.lower() not in ("binance", "mt5"):
            raise ValueError("broker must be binance or mt5")
        return value.lower()


class PaperOrderRequest(BaseModel):
    account_id: str
    symbol: str = Field(min_length=1, max_length=30)
    side: str
    quantity: float = Field(gt=0)
    reference_price: float = Field(gt=0)
    stop_loss: float = Field(gt=0)
    take_profit: float = Field(gt=0)


class SharedBacktestRequest(BaseModel):
    portfolio_id: str
    candles_by_symbol: dict[str, list[dict[str, Any]]] = Field(min_length=1, max_length=30)
    signals: list[dict[str, Any]] = Field(default_factory=list, max_length=10000)
    spread: float = Field(default=0, ge=0)
    slippage: float = Field(default=0, ge=0)
    commission_pct: float = Field(default=0, ge=0, le=5)
    max_open_trades: int | None = Field(default=None, ge=1, le=100)
    max_daily_loss_pct: float = Field(default=3, ge=0, le=100)
    max_weekly_loss_pct: float = Field(default=6, ge=0, le=100)
    max_drawdown_pct: float = Field(default=15, ge=0, le=100)


class ClosePaperOrderRequest(BaseModel):
    exit_price: float = Field(gt=0)


class RiskPositionSizeRequest(BaseModel):
    equity: float = Field(gt=0)
    risk_pct: float = Field(gt=0, le=100)
    entry: float = Field(gt=0)
    stop: float = Field(gt=0)
    max_notional_pct: float = Field(default=100.0, gt=0, le=1000)


class RiskCorrelationRequest(BaseModel):
    prices_by_symbol: dict[str, list[float]] = Field(min_length=2, max_length=50)
    min_observations: int = Field(default=20, ge=3, le=5000)


class RiskAllocationCandidate(BaseModel):
    symbol: str = Field(min_length=1, max_length=40)
    direction: str = Field(pattern="^(long|short)$")
    entry: float = Field(gt=0)
    stop: float = Field(gt=0)
    quality_score: float = Field(ge=0, le=100)
    correlation_group: str | None = Field(default=None, max_length=64)


class RiskAllocationRequest(BaseModel):
    candidates: list[RiskAllocationCandidate] = Field(min_length=1, max_length=50)
    requested_budget_pct: float | None = Field(default=None, gt=0, le=100)




class CorrelationAwareRiskAllocationRequest(BaseModel):
    candidates: list[RiskAllocationCandidate] = Field(min_length=1, max_length=50)
    prices_by_symbol: dict[str, list[float]] = Field(min_length=2, max_length=50)
    requested_budget_pct: float | None = Field(default=None, gt=0, le=100)
    correlation_penalty_strength: float = Field(default=1.0, ge=0, le=5)
    min_observations: int = Field(default=20, ge=3, le=5000)


class ForwardTestStartRequest(BaseModel):
    portfolio_id: str
    account_id: str
    symbols: list[str] = Field(min_length=1, max_length=50)
    risk_per_trade_pct: float = Field(default=0.5, gt=0, le=5)
    min_quality_score: int = Field(default=70, ge=0, le=100)
    commission_pct: float = Field(default=0.04, ge=0, le=1)
    slippage_bps: float = Field(default=2.0, ge=0, le=500)
    include_existing_signals: bool = False


class ExecutionTradeCreateRequest(BaseModel):
    portfolio_id: str
    account_id: str
    idempotency_key: str = Field(min_length=8, max_length=80)
    symbol: str = Field(min_length=1, max_length=40)
    side: str = Field(pattern="^(long|short)$")
    quantity: float = Field(gt=0)
    planned_entry: float = Field(gt=0)
    stop_loss: float = Field(gt=0)
    tp1: float = Field(gt=0)
    tp2: float = Field(gt=0)
    tp3: float = Field(gt=0)
    commission_pct: float = Field(default=0.04, ge=0, le=5)
    slippage_bps: float = Field(default=2.0, ge=0, le=1000)
    tp1_fraction: float = Field(default=0.50, gt=0, le=1)
    tp2_fraction: float = Field(default=0.30, gt=0, le=1)
    tp3_fraction: float = Field(default=0.20, gt=0, le=1)
    move_stop_to_breakeven_after_tp1: bool = True
    trailing_stop_pct: float | None = Field(default=None, gt=0, le=20)


class ExecutionTickRequest(BaseModel):
    event_id: str = Field(min_length=1, max_length=80)
    market_price: float = Field(gt=0)
    event_time_ms: int = Field(gt=0)


class ExecutionCancelRequest(BaseModel):
    event_id: str = Field(min_length=1, max_length=80)



def current_user(authorization: str | None = Header(default=None)) -> dict[str, str]:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Bearer token required")
    return authenticate_token(authorization.split(" ", 1)[1].strip())


router = APIRouter(prefix="/api/v1/v11", tags=["SmartMoney V11"])


@router.post("/auth/register", status_code=201)
def api_register(payload: RegisterRequest):
    try:
        return register_user(payload.email, payload.password)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.post("/auth/login")
def api_login(payload: LoginRequest):
    try:
        return create_session(payload.email, payload.password)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc))


@router.get("/auth/me")
def api_me(user: dict[str, str] = Depends(current_user)):
    return user


@router.post("/auth/logout")
def api_logout(authorization: str | None = Header(default=None), user=Depends(current_user)):
    token = authorization.split(" ", 1)[1].strip() if authorization else None
    revoke_session(token)
    return {"revoked": True}


@router.get("/system/readiness")
def api_readiness():
    return {
        "version": "11.0.0", "mode": "paper_only", "live_execution_enabled": False,
        "phases": {
            "market_analysis": {"status": "available", "details": "Existing SMC, MTF and V8 research engines retained"},
            "shared_portfolio_backtesting": {"status": "available", "details": "V10 shared-equity OHLC replay retained; broker margin model not included"},
            "multi_user_auth": {"status": "available", "details": "Email/password, PBKDF2 hashes, opaque expiring bearer sessions"},
            "tenant_paper_accounts": {"status": "available", "details": "Per-user portfolios, broker-labelled paper accounts and tenant-scoped orders"},
            "binance": {"status": "paper_simulation", "details": "Public market-data adapter exists; orders are simulated only"},
            "mt5": {"status": "paper_simulation", "details": "Broker-labelled paper accounts; terminal/EA bridge is not configured"},
            "forward_testing": {"status": "available", "details": "Tick-driven tenant-scoped paper forward testing with partial targets, adverse slippage, commissions and event audit trail"},
            "walk_forward_monte_carlo": {"status": "not_implemented", "details": "Requires strategy-generated historical signals and validation suite"},
            "production_deployment": {"status": "partial", "details": "Docker foundation exists; TLS, secrets vault, Redis workers and production database migration require deployment-specific work"},
        },
        "execution_allowed": False,
    }


@router.get("/brokers")
def api_brokers():
    return {"brokers": [
        {"id": "binance", "name": "Binance", "market_data": "public_api", "paper_execution": True, "live_execution": False, "status": "available_for_paper"},
        {"id": "mt5", "name": "MetaTrader 5", "market_data": "bridge_not_configured", "paper_execution": True, "live_execution": False, "status": "paper_simulator_only", "bridge_required_for_terminal_data": True},
    ], "execution_allowed": False}


@router.post("/portfolios", status_code=201)
def api_create_portfolio(payload: PortfolioRequest, user=Depends(current_user)):
    try:
        return create_portfolio(user["id"], payload.name, payload.initial_equity,
                                payload.max_open_trades, payload.max_portfolio_risk_pct,
                                payload.max_trade_risk_pct, payload.base_currency)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.get("/portfolios")
def api_list_portfolios(user=Depends(current_user)):
    return {"items": list_portfolios(user["id"])}


@router.post("/accounts", status_code=201)
def api_create_account(payload: BrokerAccountRequest, user=Depends(current_user)):
    try:
        return create_broker_account(user["id"], payload.portfolio_id, payload.broker, payload.label)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.get("/accounts")
def api_list_accounts(portfolio_id: str, user=Depends(current_user)):
    try:
        return {"items": list_broker_accounts(user["id"], portfolio_id)}
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/paper/orders", status_code=201)
def api_create_order(payload: PaperOrderRequest, user=Depends(current_user)):
    try:
        return create_paper_order(user["id"], payload.account_id, payload.symbol, payload.side,
                                  payload.quantity, payload.reference_price, payload.stop_loss,
                                  payload.take_profit)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.get("/paper/orders")
def api_list_orders(portfolio_id: str, status: str | None = None, user=Depends(current_user)):
    if status and status.lower() not in ("open", "closed"):
        raise HTTPException(status_code=422, detail="status must be open or closed")
    try:
        return {"items": list_orders(user["id"], portfolio_id, status)}
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/paper/orders/{order_id}/close")
def api_close_order(order_id: str, payload: ClosePaperOrderRequest, user=Depends(current_user)):
    try:
        return close_paper_order(user["id"], order_id, payload.exit_price)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.post("/forward/runs", status_code=201)
def api_start_forward_run(payload: ForwardTestStartRequest, user=Depends(current_user)):
    try:
        return start_forward_run(
            user["id"], payload.portfolio_id, payload.account_id, payload.symbols,
            payload.risk_per_trade_pct, payload.min_quality_score,
            payload.commission_pct, payload.slippage_bps,
            payload.include_existing_signals,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.get("/forward/runs")
def api_list_forward_runs(portfolio_id: str, limit: int = 20, user=Depends(current_user)):
    try:
        return {"items": list_forward_runs(user["id"], portfolio_id, limit)}
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.post("/forward/runs/{run_id}/stop")
def api_stop_forward_run(run_id: str, user=Depends(current_user)):
    try:
        return stop_forward_run(user["id"], run_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.get("/forward/runs/{run_id}/trades")
def api_forward_trades(run_id: str, status: str | None = None, limit: int = 200, user=Depends(current_user)):
    allowed = ("pending_entry", "open", "tp1_hit", "tp2_hit", "tp3_hit", "stopped")
    if status and status.lower() not in allowed:
        raise HTTPException(status_code=422, detail="Invalid forward-trade status")
    try:
        return {"items": list_forward_trades(user["id"], run_id, status, limit)}
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.get("/forward/runs/{run_id}/summary")
def api_forward_summary(run_id: str, user=Depends(current_user)):
    try:
        return forward_summary(user["id"], run_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.get("/forward/runs/{run_id}/comparison")
def api_forward_backtest_comparison(run_id: str, backtest_run_id: str, user=Depends(current_user)):
    try:
        return compare_forward_to_backtest(user["id"], run_id, backtest_run_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.get("/forward/trades/{trade_id}/events")
def api_forward_trade_events(trade_id: str, limit: int = 200, user=Depends(current_user)):
    try:
        return {"items": list_forward_events(user["id"], trade_id, limit)}
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.post("/backtests/shared", status_code=201)
def api_shared_backtest(payload: SharedBacktestRequest, user=Depends(current_user)):
    try:
        portfolio = get_portfolio(user["id"], payload.portfolio_id)
        from .multi_backtesting import run_multi_symbol_backtest
        result = run_multi_symbol_backtest(
            candles_by_symbol=payload.candles_by_symbol, signals=payload.signals,
            initial_equity=float(portfolio["initial_equity"]), spread=payload.spread,
            slippage=payload.slippage, commission_pct=payload.commission_pct,
            max_open_trades=payload.max_open_trades or portfolio["max_open_trades"],
            max_daily_loss_pct=payload.max_daily_loss_pct,
            max_weekly_loss_pct=payload.max_weekly_loss_pct,
            max_drawdown_pct=payload.max_drawdown_pct,
        )
        result["portfolio_id"] = payload.portfolio_id
        result["execution_allowed"] = False
        return save_backtest_run(user["id"], payload.portfolio_id, result)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.get("/backtests/shared")
def api_list_shared_backtests(portfolio_id: str, limit: int = 20, user=Depends(current_user)):
    if not 1 <= limit <= 100:
        raise HTTPException(status_code=422, detail="limit must be 1..100")
    try:
        return {"items": list_backtest_runs(user["id"], portfolio_id, limit)}
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.get("/audit")
def api_audit(limit: int = 100, user=Depends(current_user)):
    if not 1 <= limit <= 500:
        raise HTTPException(status_code=422, detail="limit must be 1..500")
    return {"items": list_audit_events(user["id"], limit)}


@router.get("/portfolios/{portfolio_id}")
def api_get_portfolio(portfolio_id: str, user=Depends(current_user)):
    try:
        return get_portfolio(user["id"], portfolio_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/risk/position-size")
def api_risk_position_size(payload: RiskPositionSizeRequest, user=Depends(current_user)):
    try:
        result = calculate_risk_position_size(**payload.model_dump())
        result["user_id"] = user["id"]
        return result
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.post("/risk/correlation")
def api_risk_correlation(payload: RiskCorrelationRequest, user=Depends(current_user)):
    try:
        result = calculate_correlation_matrix(
            payload.prices_by_symbol, payload.min_observations
        )
        result["user_id"] = user["id"]
        return result
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


def _portfolio_risk_inputs(user_id: str, portfolio_id: str):
    db = _session()
    try:
        portfolio = _owned_portfolio(db, user_id, portfolio_id)
        paper_orders = db.scalars(select(PaperOrder).where(
            PaperOrder.user_id == user_id,
            PaperOrder.portfolio_id == portfolio_id,
            PaperOrder.status == "open",
        )).all()
        forward_runs = db.scalars(select(ForwardTestRun).where(
            ForwardTestRun.user_id == user_id,
            ForwardTestRun.portfolio_id == portfolio_id,
        )).all()
        run_ids = [r.id for r in forward_runs if r.status == "active"]
        forward_trades = []
        if run_ids:
            forward_trades = db.scalars(select(ForwardTestTrade).where(
                ForwardTestTrade.user_id == user_id,
                ForwardTestTrade.portfolio_id == portfolio_id,
                ForwardTestTrade.run_id.in_(run_ids),
                ForwardTestTrade.status.in_(("pending_entry", "open", "tp1_hit", "tp2_hit")),
                ForwardTestTrade.remaining_quantity > 0,
            )).all()
        realized_paper = db.scalar(select(func.coalesce(func.sum(PaperOrder.realized_pnl), 0)).where(
            PaperOrder.user_id == user_id, PaperOrder.portfolio_id == portfolio_id,
            PaperOrder.status == "closed",
        )) or 0.0
        realized_forward = sum(float(r.realized_pnl or 0.0) for r in forward_runs)
        equity = float(portfolio.initial_equity) + float(realized_paper) + realized_forward
        if not math.isfinite(equity) or equity <= 0:
            raise ValueError("Portfolio equity is not positive")
        positions = []
        for order in paper_orders:
            positions.append({
                "symbol": order.symbol, "direction": order.side,
                "quantity": float(order.quantity), "entry_price": float(order.entry_price),
                "stop_loss": float(order.stop_loss), "risk_cash": float(order.risk_cash),
                "source": "paper_order",
            })
        for trade in forward_trades:
            qty = float(trade.remaining_quantity)
            original_qty = float(trade.quantity)
            scale = qty / original_qty if original_qty > 0 else 0.0
            entry = float(trade.actual_entry or trade.planned_entry)
            positions.append({
                "symbol": trade.symbol, "direction": trade.direction,
                "quantity": qty, "entry_price": entry,
                "stop_loss": float(trade.stop_loss),
                "risk_cash": max(0.0, float(trade.risk_cash) * scale),
                "source": "forward_test",
            })
        execution_trades = db.scalars(select(ExecutionTrade).where(
            ExecutionTrade.user_id == user_id,
            ExecutionTrade.portfolio_id == portfolio_id,
            ExecutionTrade.status.in_(("pending_entry", "open", "partially_closed")),
            ExecutionTrade.remaining_quantity > 0,
        )).all()
        for trade in execution_trades:
            qty = float(trade.remaining_quantity)
            entry = float(trade.avg_entry_price or trade.planned_entry)
            positions.append({
                "symbol": trade.symbol, "direction": trade.side,
                "quantity": qty, "entry_price": entry,
                "stop_loss": float(trade.stop_loss),
                "risk_cash": max(0.0, (entry - float(trade.stop_loss)) * qty) if trade.side == "long" else max(0.0, (float(trade.stop_loss) - entry) * qty),
                "source": "paper_execution",
            })
        # TP1/TP2 may realize PnL while a trade remains open. Include it in
        # equity immediately; filtering to closed trades understates equity/risk capacity.
        realized_execution = db.scalar(select(func.coalesce(func.sum(ExecutionTrade.realized_pnl - ExecutionTrade.fees_paid), 0)).where(
            ExecutionTrade.user_id == user_id,
            ExecutionTrade.portfolio_id == portfolio_id,
        )) or 0.0
        equity += float(realized_execution)
        return {
            "equity": equity,
            "positions": positions,
            "max_portfolio_risk_pct": float(portfolio.max_portfolio_risk_pct),
            "max_trade_risk_pct": float(portfolio.max_trade_risk_pct),
            "max_open_trades": int(portfolio.max_open_trades),
            "portfolio_id": portfolio_id,
            "paper_position_count": len(paper_orders),
            "forward_position_count": len(forward_trades),
            "execution_position_count": len(execution_trades),
        }
    finally:
        db.close()


@router.get("/portfolios/{portfolio_id}/risk")
def api_portfolio_risk_assessment(portfolio_id: str, user=Depends(current_user)):
    try:
        snapshot = _portfolio_risk_inputs(user["id"], portfolio_id)
        report = assess_portfolio_risk(
            equity=snapshot["equity"], positions=snapshot["positions"],
            max_portfolio_risk_pct=snapshot["max_portfolio_risk_pct"],
            max_trade_risk_pct=snapshot["max_trade_risk_pct"],
            max_open_trades=snapshot["max_open_trades"],
        )
        report.update({
            "portfolio_id": portfolio_id,
            "paper_position_count": snapshot["paper_position_count"],
            "forward_position_count": snapshot["forward_position_count"],
            "execution_position_count": snapshot["execution_position_count"],
            "data_scope": "open legacy paper orders, active forward-test trades, and phase 9 paper execution trades",
        })
        return report
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.post("/portfolios/{portfolio_id}/risk/allocate")
def api_portfolio_risk_allocate(
    portfolio_id: str, payload: RiskAllocationRequest, user=Depends(current_user)
):
    try:
        snapshot = _portfolio_risk_inputs(user["id"], portfolio_id)
        report = allocate_capital(
            equity=snapshot["equity"],
            candidates=[x.model_dump() for x in payload.candidates],
            current_open_risk_cash=sum(float(x["risk_cash"]) for x in snapshot["positions"]),
            max_portfolio_risk_pct=snapshot["max_portfolio_risk_pct"],
            max_trade_risk_pct=snapshot["max_trade_risk_pct"],
            max_open_trades=snapshot["max_open_trades"],
            current_open_positions=len(snapshot["positions"]),
            requested_budget_pct=payload.requested_budget_pct,
        )
        report["portfolio_id"] = portfolio_id
        return report
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.post("/portfolios/{portfolio_id}/risk/allocate-correlated")
def api_portfolio_risk_allocate_correlated(
    portfolio_id: str,
    payload: CorrelationAwareRiskAllocationRequest,
    user=Depends(current_user),
):
    """Return correlation-adjusted paper allocation suggestions; never submits orders."""
    try:
        snapshot = _portfolio_risk_inputs(user["id"], portfolio_id)
        report = allocate_capital_with_correlation(
            equity=snapshot["equity"],
            candidates=[x.model_dump() for x in payload.candidates],
            prices_by_symbol=payload.prices_by_symbol,
            current_open_risk_cash=sum(float(x["risk_cash"]) for x in snapshot["positions"]),
            max_portfolio_risk_pct=snapshot["max_portfolio_risk_pct"],
            max_trade_risk_pct=snapshot["max_trade_risk_pct"],
            max_open_trades=snapshot["max_open_trades"],
            current_open_positions=len(snapshot["positions"]),
            requested_budget_pct=payload.requested_budget_pct,
            correlation_penalty_strength=payload.correlation_penalty_strength,
            min_observations=payload.min_observations,
        )
        report["portfolio_id"] = portfolio_id
        return report
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


# ---------------------------------------------------------------------------
# Phase 9: persistent paper execution. This service never calls a broker.
# ---------------------------------------------------------------------------

def _execution_state(trade: ExecutionTrade) -> dict[str, Any]:
    return {
        "side": trade.side, "status": trade.status,
        "planned_entry": float(trade.planned_entry),
        "avg_entry_price": float(trade.avg_entry_price) if trade.avg_entry_price is not None else None,
        "stop_loss": float(trade.stop_loss), "initial_stop_loss": float(trade.initial_stop_loss),
        "tp1": float(trade.tp1), "tp2": float(trade.tp2), "tp3": float(trade.tp3),
        "quantity": float(trade.quantity), "remaining_quantity": float(trade.remaining_quantity),
        "tp1_fraction": float(trade.tp1_fraction), "tp2_fraction": float(trade.tp2_fraction),
        "tp3_fraction": float(trade.tp3_fraction), "tp1_hit": bool(trade.tp1_hit),
        "tp2_hit": bool(trade.tp2_hit), "tp3_hit": bool(trade.tp3_hit),
        "move_stop_to_breakeven_after_tp1": bool(trade.move_stop_to_breakeven_after_tp1),
        "trailing_stop_pct": float(trade.trailing_stop_pct) if trade.trailing_stop_pct is not None else None,
        "high_water": float(trade.high_water) if trade.high_water is not None else None,
        "low_water": float(trade.low_water) if trade.low_water is not None else None,
        "commission_pct": float(trade.commission_pct), "slippage_bps": float(trade.slippage_bps),
        "realized_pnl": float(trade.realized_pnl), "fees_paid": float(trade.fees_paid),
        "last_price": float(trade.last_price) if trade.last_price is not None else None,
        "last_event_time_ms": int(trade.last_event_time_ms),
        "entry_filled_at_ms": trade.entry_filled_at_ms, "closed_at_ms": trade.closed_at_ms,
    }


def _execution_trade_dict(trade: ExecutionTrade) -> dict[str, Any]:
    state = _execution_state(trade)
    return {
        "id": trade.id, "user_id": trade.user_id, "portfolio_id": trade.portfolio_id,
        "account_id": trade.account_id, "broker": trade.broker, "symbol": trade.symbol,
        "idempotency_key": trade.idempotency_key, **state,
        "net_realized_pnl": round(state["realized_pnl"] - state["fees_paid"], 8),
        "mode": "paper", "execution_allowed": False,
        "created_at": _iso(trade.created_at), "updated_at": _iso(trade.updated_at),
    }



def _execution_request_matches(existing: ExecutionTrade, payload: ExecutionTradeCreateRequest,
                               symbol: str, plan: dict[str, Any]) -> bool:
    numeric = (
        (existing.quantity, plan["quantity"]),
        (existing.planned_entry, plan["planned_entry"]),
        (existing.initial_stop_loss, plan["stop_loss"]),
        (existing.tp1, plan["tp1"]), (existing.tp2, plan["tp2"]),
        (existing.tp3, plan["tp3"]),
        (existing.commission_pct, plan["commission_pct"]),
        (existing.slippage_bps, plan["slippage_bps"]),
        (existing.tp1_fraction, plan["tp1_fraction"]),
        (existing.tp2_fraction, plan["tp2_fraction"]),
        (existing.tp3_fraction, plan["tp3_fraction"]),
    )
    return (
        existing.portfolio_id == payload.portfolio_id
        and existing.account_id == payload.account_id
        and existing.symbol == symbol
        and existing.side == plan["side"]
        and all(math.isclose(float(a), float(b), rel_tol=0, abs_tol=1e-12) for a, b in numeric)
        and existing.move_stop_to_breakeven_after_tp1 == payload.move_stop_to_breakeven_after_tp1
        and ((existing.trailing_stop_pct is None and plan["trailing_stop_pct"] is None)
             or (existing.trailing_stop_pct is not None and plan["trailing_stop_pct"] is not None
                 and math.isclose(float(existing.trailing_stop_pct), float(plan["trailing_stop_pct"]), rel_tol=0, abs_tol=1e-12)))
    )



def create_execution_trade(user_id: str, payload: ExecutionTradeCreateRequest) -> dict[str, Any]:
    symbol = payload.symbol.strip().upper()
    if not symbol or not symbol.replace("_", "").isalnum():
        raise ValueError("Invalid symbol")
    plan = validate_execution_plan(
        side=payload.side, quantity=payload.quantity, planned_entry=payload.planned_entry,
        stop_loss=payload.stop_loss, tp1=payload.tp1, tp2=payload.tp2, tp3=payload.tp3,
        commission_pct=payload.commission_pct, slippage_bps=payload.slippage_bps,
        target_fractions=(payload.tp1_fraction, payload.tp2_fraction, payload.tp3_fraction),
        trailing_stop_pct=payload.trailing_stop_pct,
    )
    db = _session()
    try:
        existing = db.scalar(select(ExecutionTrade).where(
            ExecutionTrade.user_id == user_id,
            ExecutionTrade.idempotency_key == payload.idempotency_key,
        ))
        if existing:
            if not _execution_request_matches(existing, payload, symbol, plan):
                raise ValueError("Idempotency key was already used for a different execution request")
            return {**_execution_trade_dict(existing), "idempotent_replay": True}

        joined = db.execute(
            select(BrokerAccount, Portfolio)
            .join(Portfolio, Portfolio.id == BrokerAccount.portfolio_id)
            .where(BrokerAccount.id == payload.account_id,
                   BrokerAccount.user_id == user_id,
                   Portfolio.id == payload.portfolio_id,
                   Portfolio.user_id == user_id)
            .with_for_update(of=Portfolio)
        ).first()
        if joined is None:
            raise LookupError("Paper account or portfolio not found")
        account, portfolio = joined
        if account.mode != "paper":
            raise ValueError("Phase 9 accepts paper accounts only")

        legacy_orders = db.scalars(select(PaperOrder).where(
            PaperOrder.user_id == user_id, PaperOrder.portfolio_id == portfolio.id,
            PaperOrder.status == "open")).all()
        all_forward_runs = db.scalars(select(ForwardTestRun).where(
            ForwardTestRun.user_id == user_id, ForwardTestRun.portfolio_id == portfolio.id)).all()
        active_runs = [r for r in all_forward_runs if r.status == "active"]
        active_run_ids = [r.id for r in active_runs]
        forward_trades = db.scalars(select(ForwardTestTrade).where(
            ForwardTestTrade.user_id == user_id, ForwardTestTrade.portfolio_id == portfolio.id,
            ForwardTestTrade.run_id.in_(active_run_ids) if active_run_ids else False,
            ForwardTestTrade.status.in_(("pending_entry", "open", "tp1_hit", "tp2_hit")),
            ForwardTestTrade.remaining_quantity > 0)).all()
        execution_trades = db.scalars(select(ExecutionTrade).where(
            ExecutionTrade.user_id == user_id, ExecutionTrade.portfolio_id == portfolio.id,
            ExecutionTrade.status.in_(("pending_entry", "open", "partially_closed")),
            ExecutionTrade.remaining_quantity > 0)).all()

        realized_paper = db.scalar(select(func.coalesce(func.sum(PaperOrder.realized_pnl), 0)).where(
            PaperOrder.user_id == user_id, PaperOrder.portfolio_id == portfolio.id,
            PaperOrder.status == "closed")) or 0.0
        realized_forward = sum(float(r.realized_pnl or 0.0) - float(r.fees_paid or 0.0) for r in all_forward_runs)
        # Include realized partial exits from still-active execution trades.
        realized_execution = db.scalar(select(func.coalesce(func.sum(ExecutionTrade.realized_pnl - ExecutionTrade.fees_paid), 0)).where(
            ExecutionTrade.user_id == user_id, ExecutionTrade.portfolio_id == portfolio.id)) or 0.0
        equity = float(portfolio.initial_equity) + float(realized_paper) + realized_forward + float(realized_execution)
        if not math.isfinite(equity) or equity <= 0:
            raise ValueError("Portfolio equity is not positive")

        positions = []
        for order in legacy_orders:
            positions.append({"symbol": order.symbol, "direction": order.side,
                "quantity": float(order.quantity), "entry_price": float(order.entry_price),
                "stop_loss": float(order.stop_loss), "risk_cash": float(order.risk_cash)})
        for item in forward_trades:
            qty = float(item.remaining_quantity)
            scale = qty / float(item.quantity) if float(item.quantity) > 0 else 0.0
            entry = float(item.actual_entry or item.planned_entry)
            positions.append({"symbol": item.symbol, "direction": item.direction,
                "quantity": qty, "entry_price": entry, "stop_loss": float(item.stop_loss),
                "risk_cash": max(0.0, float(item.risk_cash) * scale)})
        for item in execution_trades:
            qty = float(item.remaining_quantity)
            entry = float(item.avg_entry_price or item.planned_entry)
            positions.append({"symbol": item.symbol, "direction": item.side,
                "quantity": qty, "entry_price": entry, "stop_loss": float(item.stop_loss),
                "risk_cash": max(0.0, (entry - float(item.stop_loss)) * qty) if item.side == "long" else max(0.0, (float(item.stop_loss) - entry) * qty)})

        requested_risk = abs(float(payload.planned_entry) - float(payload.stop_loss)) * float(payload.quantity)
        if requested_risk / equity * 100 > float(portfolio.max_trade_risk_pct) + 1e-9:
            raise ValueError("Per-trade risk limit exceeded")
        aggregate_risk = sum(float(x["risk_cash"]) for x in positions) + requested_risk
        if aggregate_risk / equity * 100 > float(portfolio.max_portfolio_risk_pct) + 1e-9:
            raise ValueError("Portfolio aggregate open-risk limit exceeded")
        if len(positions) + 1 > int(portfolio.max_open_trades):
            raise ValueError("Portfolio max_open_trades limit reached")

        now = _now()
        trade = ExecutionTrade(
            id=str(uuid.uuid4()), user_id=user_id, portfolio_id=portfolio.id,
            account_id=account.id, broker=account.broker, idempotency_key=payload.idempotency_key,
            symbol=symbol, side=plan["side"], status="pending_entry",
            planned_entry=plan["planned_entry"], avg_entry_price=None,
            stop_loss=plan["stop_loss"], initial_stop_loss=plan["stop_loss"],
            tp1=plan["tp1"], tp2=plan["tp2"], tp3=plan["tp3"],
            quantity=plan["quantity"], remaining_quantity=plan["quantity"],
            tp1_fraction=plan["tp1_fraction"], tp2_fraction=plan["tp2_fraction"], tp3_fraction=plan["tp3_fraction"],
            move_stop_to_breakeven_after_tp1=payload.move_stop_to_breakeven_after_tp1,
            trailing_stop_pct=plan["trailing_stop_pct"], commission_pct=plan["commission_pct"],
            slippage_bps=plan["slippage_bps"], realized_pnl=0.0, fees_paid=0.0,
            last_event_time_ms=0, created_at=now, updated_at=now,
        )
        db.add(trade)
        db.flush()
        db.add(ExecutionEvent(
            trade_id=trade.id, source_event_id="ORDER_CREATED", sequence_no=0,
            event_type="ORDER_CREATED", market_price=plan["planned_entry"],
            fill_price=None, quantity=plan["quantity"], pnl=0.0, fee=0.0,
            event_time_ms=int(now.timestamp() * 1000), event_time=now,
            details_json={"mode": "paper", "broker": account.broker, "live_execution": False},
        ))
        _audit(db, user_id, "PAPER_EXECUTION_CREATED", portfolio.id, trade.id,
               {"symbol": symbol, "side": plan["side"], "quantity": plan["quantity"], "idempotency_key": payload.idempotency_key})
        db.commit()
        db.refresh(trade)
        return {**_execution_trade_dict(trade), "idempotent_replay": False}
    except IntegrityError:
        db.rollback()
        existing = db.scalar(select(ExecutionTrade).where(
            ExecutionTrade.user_id == user_id,
            ExecutionTrade.idempotency_key == payload.idempotency_key,
        ))
        if existing:
            if not _execution_request_matches(existing, payload, symbol, plan):
                raise ValueError("Idempotency key was already used for a different execution request")
            return {**_execution_trade_dict(existing), "idempotent_replay": True}
        raise
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def list_execution_trades(user_id: str, portfolio_id: str, status: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
    if not 1 <= int(limit) <= 500:
        raise ValueError("limit must be between 1 and 500")
    db = _session()
    try:
        _owned_portfolio(db, user_id, portfolio_id)
        query = select(ExecutionTrade).where(
            ExecutionTrade.user_id == user_id, ExecutionTrade.portfolio_id == portfolio_id)
        if status:
            if status not in ("pending_entry", "open", "partially_closed", "closed", "cancelled"):
                raise ValueError("Invalid execution-trade status")
            query = query.where(ExecutionTrade.status == status)
        rows = db.scalars(query.order_by(ExecutionTrade.created_at.desc()).limit(limit)).all()
        return [_execution_trade_dict(x) for x in rows]
    finally:
        db.close()


def get_execution_trade(user_id: str, trade_id: str) -> dict[str, Any]:
    db = _session()
    try:
        trade = db.scalar(select(ExecutionTrade).where(
            ExecutionTrade.id == trade_id, ExecutionTrade.user_id == user_id))
        if trade is None:
            raise LookupError("Execution trade not found")
        return _execution_trade_dict(trade)
    finally:
        db.close()


def process_execution_tick(user_id: str, trade_id: str, payload: ExecutionTickRequest, force_close: bool = False) -> dict[str, Any]:
    db = _session()
    try:
        trade = db.scalar(select(ExecutionTrade).where(
            ExecutionTrade.id == trade_id, ExecutionTrade.user_id == user_id).with_for_update())
        if trade is None:
            raise LookupError("Execution trade not found")
        duplicate = trade.last_event_id == payload.event_id or db.scalar(select(ExecutionEvent).where(
            ExecutionEvent.trade_id == trade.id,
            ExecutionEvent.source_event_id == payload.event_id).limit(1)) is not None
        if duplicate:
            return {**_execution_trade_dict(trade), "idempotent_replay": True,
                    "events": [], "message": "Duplicate market event ignored"}
        updated, generated = process_trade_tick(
            _execution_state(trade), market_price=payload.market_price,
            event_time_ms=payload.event_time_ms, event_id=payload.event_id,
            force_close=force_close,
        )
        for key, value in updated.items():
            if hasattr(trade, key):
                setattr(trade, key, value)
        now = _now()
        trade.updated_at = now
        trade.last_event_id = payload.event_id
        event_time = datetime.fromtimestamp(payload.event_time_ms / 1000.0, tz=timezone.utc)
        journal_events = [item for item in generated if item["event_type"] != "PRICE_OBSERVED"]
        for seq, item in enumerate(journal_events):
            db.add(ExecutionEvent(
                trade_id=trade.id, source_event_id=payload.event_id, sequence_no=seq,
                event_type=item["event_type"], market_price=item["market_price"],
                fill_price=item["fill_price"], quantity=item["quantity"], pnl=item["pnl"],
                fee=item["fee"], event_time_ms=payload.event_time_ms, event_time=event_time,
                details_json=item["details"],
            ))
            if item["event_type"] not in ("PRICE_OBSERVED", "TRAILING_STOP_UPDATED", "STOP_MOVED_TO_BREAKEVEN"):
                _audit(db, user_id, "PAPER_EXECUTION_" + item["event_type"], trade.portfolio_id,
                       trade.id, {"event_id": payload.event_id, "quantity": item["quantity"],
                                  "fill_price": item["fill_price"], "pnl": item["pnl"], "fee": item["fee"]})
        db.commit()
        db.refresh(trade)
        return {**_execution_trade_dict(trade), "idempotent_replay": False,
                "events": generated, "message": "Paper market event processed; no broker order was sent"}
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def cancel_execution_trade(user_id: str, trade_id: str, event_id: str) -> dict[str, Any]:
    db = _session()
    try:
        trade = db.scalar(select(ExecutionTrade).where(
            ExecutionTrade.id == trade_id, ExecutionTrade.user_id == user_id).with_for_update())
        if trade is None:
            raise LookupError("Execution trade not found")
        duplicate = trade.last_event_id == event_id or db.scalar(select(ExecutionEvent).where(
            ExecutionEvent.trade_id == trade.id, ExecutionEvent.source_event_id == event_id).limit(1)) is not None
        if duplicate:
            return {**_execution_trade_dict(trade), "idempotent_replay": True}
        updated = cancel_pending_trade(_execution_state(trade))
        trade.status = updated["status"]
        trade.remaining_quantity = updated["remaining_quantity"]
        trade.updated_at = _now()
        trade.last_event_id = event_id
        event_time_ms = int(trade.updated_at.timestamp() * 1000)
        db.add(ExecutionEvent(
            trade_id=trade.id, source_event_id=event_id, sequence_no=0,
            event_type="ORDER_CANCELLED", market_price=float(trade.last_price or trade.planned_entry),
            fill_price=None, quantity=0.0, pnl=0.0, fee=0.0,
            event_time_ms=event_time_ms, event_time=trade.updated_at,
            details_json={"reason": "user_cancelled_pending_entry"},
        ))
        _audit(db, user_id, "PAPER_EXECUTION_CANCELLED", trade.portfolio_id, trade.id, {"event_id": event_id})
        db.commit()
        db.refresh(trade)
        return {**_execution_trade_dict(trade), "idempotent_replay": False}
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()



def active_execution_symbols() -> list[str]:
    """Symbols with active Binance paper executions for the live market monitor."""
    db = _session()
    try:
        rows = db.scalars(select(ExecutionTrade.symbol).where(
            ExecutionTrade.broker == "binance",
            ExecutionTrade.status.in_(("pending_entry", "open", "partially_closed")),
            ExecutionTrade.remaining_quantity > 0,
        ).distinct()).all()
        return sorted({str(x).upper() for x in rows})
    finally:
        db.close()


def process_active_execution_market_event(event: dict[str, Any]) -> int:
    """Fan one accepted public Binance trade tick into all matching paper trades."""
    symbol = str(event.get("symbol", "")).strip().upper()
    if not symbol:
        return 0
    db = _session()
    try:
        trade_ids = db.execute(select(ExecutionTrade.user_id, ExecutionTrade.id).where(
            ExecutionTrade.broker == "binance", ExecutionTrade.symbol == symbol,
            ExecutionTrade.status.in_(("pending_entry", "open", "partially_closed")),
            ExecutionTrade.remaining_quantity > 0,
        )).all()
    finally:
        db.close()
    raw_event_id = event.get("event_id")
    event_id = f"binance:{raw_event_id}" if raw_event_id is not None else f"binance:{event.get('event_time_ms')}:{float(event['price']):.12g}"
    event_id = event_id[:80]
    processed = 0
    for owner_id, trade_id in trade_ids:
        try:
            process_execution_tick(owner_id, trade_id, ExecutionTickRequest(
                event_id=event_id, market_price=float(event["price"]),
                event_time_ms=int(event["event_time_ms"]),
            ))
            processed += 1
        except ValueError as exc:
            # A replayed/out-of-order feed event must not stop other tenants' trades.
            if "chronological" not in str(exc) and "terminal" not in str(exc):
                raise
    return processed



def list_execution_events(user_id: str, trade_id: str, limit: int = 200) -> list[dict[str, Any]]:
    if not 1 <= int(limit) <= 1000:
        raise ValueError("limit must be between 1 and 1000")
    db = _session()
    try:
        trade = db.scalar(select(ExecutionTrade).where(
            ExecutionTrade.id == trade_id, ExecutionTrade.user_id == user_id))
        if trade is None:
            raise LookupError("Execution trade not found")
        rows = db.scalars(select(ExecutionEvent).where(
            ExecutionEvent.trade_id == trade_id).order_by(ExecutionEvent.id).limit(limit)).all()
        return [{"id": x.id, "source_event_id": x.source_event_id,
                 "event_type": x.event_type, "market_price": x.market_price,
                 "fill_price": x.fill_price, "quantity": x.quantity, "pnl": x.pnl,
                 "fee": x.fee, "event_time_ms": x.event_time_ms,
                 "event_time": _iso(x.event_time), "details": x.details_json} for x in rows]
    finally:
        db.close()


@router.post("/execution/paper/trades", status_code=201)
def api_create_execution_trade(payload: ExecutionTradeCreateRequest, user=Depends(current_user)):
    try:
        return create_execution_trade(user["id"], payload)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.get("/execution/paper/trades")
def api_list_execution_trades(portfolio_id: str, status: str | None = None, limit: int = 100, user=Depends(current_user)):
    try:
        return {"items": list_execution_trades(user["id"], portfolio_id, status, limit),
                "mode": "paper", "execution_allowed": False}
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.get("/execution/paper/trades/{trade_id}")
def api_get_execution_trade(trade_id: str, user=Depends(current_user)):
    try:
        return get_execution_trade(user["id"], trade_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/execution/paper/trades/{trade_id}/ticks")
def api_process_execution_tick(trade_id: str, payload: ExecutionTickRequest, user=Depends(current_user)):
    try:
        return process_execution_tick(user["id"], trade_id, payload)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.post("/execution/paper/trades/{trade_id}/close")
def api_close_execution_trade(trade_id: str, payload: ExecutionTickRequest, user=Depends(current_user)):
    try:
        return process_execution_tick(user["id"], trade_id, payload, force_close=True)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.post("/execution/paper/trades/{trade_id}/cancel")
def api_cancel_execution_trade(trade_id: str, payload: ExecutionCancelRequest, user=Depends(current_user)):
    try:
        return cancel_execution_trade(user["id"], trade_id, payload.event_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.get("/execution/paper/trades/{trade_id}/events")
def api_execution_events(trade_id: str, limit: int = 200, user=Depends(current_user)):
    try:
        return {"items": list_execution_events(user["id"], trade_id, limit)}
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


from .performance_analytics import build_portfolio_performance


@router.get("/portfolios/{portfolio_id}/performance")
def api_portfolio_performance(
    portfolio_id: str,
    limit: int = 500,
    user=Depends(current_user),
):
    """Return realized paper-execution performance analytics for an owned portfolio."""
    if not 1 <= limit <= 500:
        raise HTTPException(status_code=422, detail="limit must be between 1 and 500")
    try:
        portfolio = get_portfolio(user["id"], portfolio_id)
        trades = list_execution_trades(user["id"], portfolio_id, status=None, limit=limit)
        result = build_portfolio_performance(
            initial_equity=float(portfolio["initial_equity"]),
            trades=trades,
            requested_limit=limit,
        )
        result["portfolio_id"] = portfolio_id
        result["portfolio_name"] = portfolio["name"]
        result["truncated"] = len(trades) >= limit
        return result
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


from .strategy_validation import build_strategy_validation


@router.get("/portfolios/{portfolio_id}/validation")
def api_portfolio_statistical_validation(
    portfolio_id: str,
    limit: int = 500,
    bootstrap_iterations: int = 2000,
    user=Depends(current_user),
):
    """Return descriptive statistical validation for closed paper execution trades."""
    if not 1 <= limit <= 500:
        raise HTTPException(status_code=422, detail="limit must be between 1 and 500")
    if not 500 <= bootstrap_iterations <= 10000:
        raise HTTPException(status_code=422, detail="bootstrap_iterations must be between 500 and 10000")
    try:
        portfolio = get_portfolio(user["id"], portfolio_id)
        trades = list_execution_trades(user["id"], portfolio_id, status=None, limit=limit)
        result = build_strategy_validation(
            trades=trades, bootstrap_iterations=bootstrap_iterations
        )
        result["portfolio_id"] = portfolio_id
        result["portfolio_name"] = portfolio["name"]
        result["trades_returned"] = len(trades)
        result["truncated"] = len(trades) >= limit
        return result
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


from .walk_forward_validation import build_walk_forward_validation


@router.get("/portfolios/{portfolio_id}/walk-forward")
def api_portfolio_walk_forward_validation(
    portfolio_id: str,
    limit: int = 500,
    folds: int = 4,
    min_train_fraction: float = 0.5,
    user=Depends(current_user),
):
    """Chronological holdout diagnostics for closed paper execution outcomes."""
    if not 1 <= limit <= 500:
        raise HTTPException(status_code=422, detail="limit must be between 1 and 500")
    try:
        portfolio = get_portfolio(user["id"], portfolio_id)
        trades = list_execution_trades(user["id"], portfolio_id, status=None, limit=limit)
        result = build_walk_forward_validation(
            trades=trades, folds=folds, min_train_fraction=min_train_fraction
        )
        result["portfolio_id"] = portfolio_id
        result["portfolio_name"] = portfolio["name"]
        result["trades_returned"] = len(trades)
        result["truncated"] = len(trades) >= limit
        return result
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


from .monte_carlo_research import run_monte_carlo
from .robustness_research import build_robustness_report
from .research_final_audit import build_research_audit


@router.get("/portfolios/{portfolio_id}/monte-carlo")
def api_portfolio_monte_carlo(
    portfolio_id: str, limit: int = 500, simulations: int = 2000, horizon: int = 100,
    user=Depends(current_user),
):
    if not 1 <= limit <= 500:
        raise HTTPException(status_code=422, detail="limit must be between 1 and 500")
    try:
        portfolio = get_portfolio(user["id"], portfolio_id)
        trades = list_execution_trades(user["id"], portfolio_id, status=None, limit=limit)
        result = run_monte_carlo(trades=trades, simulations=simulations, horizon=horizon)
        result.update({"portfolio_id": portfolio_id, "portfolio_name": portfolio["name"],
                       "trades_returned": len(trades), "truncated": len(trades) >= limit})
        return result
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.get("/portfolios/{portfolio_id}/robustness")
def api_portfolio_robustness(
    portfolio_id: str, limit: int = 500, cost_stress_r: float = 0.05, windows: int = 4,
    user=Depends(current_user),
):
    if not 1 <= limit <= 500:
        raise HTTPException(status_code=422, detail="limit must be between 1 and 500")
    try:
        portfolio = get_portfolio(user["id"], portfolio_id)
        trades = list_execution_trades(user["id"], portfolio_id, status=None, limit=limit)
        result = build_robustness_report(trades=trades, cost_stress_r=cost_stress_r, windows=windows)
        result.update({"portfolio_id": portfolio_id, "portfolio_name": portfolio["name"],
                       "trades_returned": len(trades), "truncated": len(trades) >= limit})
        return result
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.get("/portfolios/{portfolio_id}/research-audit")
def api_portfolio_research_audit(
    portfolio_id: str, limit: int = 500, user=Depends(current_user),
):
    if not 1 <= limit <= 500:
        raise HTTPException(status_code=422, detail="limit must be between 1 and 500")
    try:
        portfolio = get_portfolio(user["id"], portfolio_id)
        trades = list_execution_trades(user["id"], portfolio_id, status=None, limit=limit)
        result = build_research_audit(trades=trades, portfolio=portfolio)
        result.update({"portfolio_id": portfolio_id, "portfolio_name": portfolio["name"],
                       "trades_returned": len(trades), "truncated": len(trades) >= limit})
        return result
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))



# ===== TRADF PHASES 16-20: additive research, operations and release routes =====
# This block is appended once by the installation script. Existing routes remain intact.
from pydantic import BaseModel as _Phase1520BaseModel, Field as _Phase1520Field
from .historical_optimizer import optimize_historical_smc as _phase16_optimize
from .strategy_portfolio_intelligence import allocate_strategy_weights as _phase17_allocate
from .production_observability import build_operational_report as _phase18_report
from .security_release_audit import build_security_audit as _phase19_security, build_release_audit as _phase20_release
from .historical_smc_backtest import run_historical_smc_portfolio_backtest as _phase16_runner
from .performance_analytics import build_portfolio_performance as _phase10_performance
from .strategy_validation import build_strategy_validation as _phase11_validation
from .walk_forward_validation import build_walk_forward_validation as _phase12_walk_forward
from .research_final_audit import build_research_audit as _phase15_research_audit
from .database import get_session_factory as _phase18_session_factory


class _Phase16OptimizeRequest(_Phase1520BaseModel):
    candles_by_symbol_and_tf: dict[str, dict[str, list[dict[str, Any]]]]
    initial_equity: float = 10000.0
    risk_percent: float = 0.5
    min_quality_scores: list[int] = _Phase1520Field(default_factory=lambda: [60, 65, 70])
    min_rr_values: list[float] = _Phase1520Field(default_factory=lambda: [1.5, 2.0, 2.5])
    train_fraction: float = 0.7
    max_combinations: int = 24
    min_train_trades: int = 5
    spread: float = 0.0
    slippage: float = 0.0
    commission_pct: float = 0.0


class _Phase17AllocationRequest(_Phase1520BaseModel):
    strategies: list[dict[str, Any]]
    correlation: list[list[float]] | None = None
    max_weight: float = 0.4
    min_edge: float = 0.0


@router.post("/research/historical-optimization")
def api_phase16_historical_optimization(payload: _Phase16OptimizeRequest, user=Depends(current_user)):
    """Run bounded parameter selection on OHLC training data and one untouched chronological holdout."""
    try:
        result = _phase16_optimize(
            candles_by_symbol_and_tf=payload.candles_by_symbol_and_tf,
            runner=_phase16_runner,
            initial_equity=payload.initial_equity,
            risk_percent=payload.risk_percent,
            min_quality_scores=payload.min_quality_scores,
            min_rr_values=payload.min_rr_values,
            train_fraction=payload.train_fraction,
            max_combinations=payload.max_combinations,
            min_train_trades=payload.min_train_trades,
            costs={"spread": payload.spread, "slippage": payload.slippage,
                    "commission_pct": payload.commission_pct},
        )
        result["requested_by"] = str(user.get("id"))
        return result
    except (ValueError, KeyError, TypeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.post("/research/strategy-allocation")
def api_phase17_strategy_allocation(payload: _Phase17AllocationRequest, user=Depends(current_user)):
    try:
        return _phase17_allocate(strategies=payload.strategies, correlation=payload.correlation,
                                 max_weight=payload.max_weight, min_edge=payload.min_edge)
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.get("/operations/monitoring")
def api_phase18_operational_monitoring(user=Depends(current_user)):
    return _phase18_report(session_factory=_phase18_session_factory(), live_execution_enabled=False)


@router.get("/portfolios/{portfolio_id}/security-audit")
def api_phase19_security_audit(portfolio_id: str, user=Depends(current_user)):
    try:
        portfolio = get_portfolio(user["id"], portfolio_id)
        return _phase19_security(authenticated_user=user, portfolio=portfolio, live_execution_enabled=False)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.get("/portfolios/{portfolio_id}/release-audit")
def api_phase20_release_audit(portfolio_id: str, limit: int = 500, user=Depends(current_user)):
    if not 1 <= limit <= 500:
        raise HTTPException(status_code=422, detail="limit must be between 1 and 500")
    try:
        portfolio = get_portfolio(user["id"], portfolio_id)
        trades = list_execution_trades(user["id"], portfolio_id, status=None, limit=limit)
        performance = _phase10_performance(initial_equity=float(portfolio["initial_equity"]),
                                           trades=trades, requested_limit=limit)
        validation = _phase11_validation(trades=trades, bootstrap_iterations=1000)
        walk_forward = _phase12_walk_forward(trades=trades, folds=4, min_train_fraction=0.5)
        research_audit = _phase15_research_audit(trades=trades, portfolio=portfolio)
        security_audit = _phase19_security(authenticated_user=user, portfolio=portfolio,
                                           live_execution_enabled=False)
        operational = _phase18_report(session_factory=_phase18_session_factory(), live_execution_enabled=False)
        result = _phase20_release(performance=performance, validation=validation,
                                  walk_forward=walk_forward, research_audit=research_audit,
                                  security_audit=security_audit, operational_report=operational)
        result.update({"portfolio_id": portfolio_id, "portfolio_name": portfolio["name"],
                       "trades_returned": len(trades), "truncated": len(trades) >= limit})
        return result
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

# ===== END TRADF PHASES 16-20 =====



# ===== TRADF PHASES 21-25: paper operations, adaptive risk and reliability =====
from pydantic import BaseModel as _Phase2125BaseModel, Field as _Phase2125Field
from .phase21_paper_control import build_paper_control_report as _phase21_paper_control
from .phase22_execution_controls import build_execution_preflight as _phase22_preflight
from .phase23_adaptive_risk import recommend_adaptive_risk as _phase23_adaptive_risk
from .phase24_realtime_intelligence import build_trade_alerts as _phase24_alerts
from .phase25_reliability import build_reliability_report as _phase25_reliability


def _phase2125_context(user_id: str, portfolio_id: str, limit: int = 500):
    portfolio = get_portfolio(user_id, portfolio_id)
    trades = list_execution_trades(user_id, portfolio_id, status=None, limit=limit)
    trade_ids = [trade["id"] for trade in trades]
    events_by_trade: dict[str, list[dict[str, Any]]] = {trade_id: [] for trade_id in trade_ids}
    if trade_ids:
        db = _session()
        try:
            rows = db.scalars(
                select(ExecutionEvent)
                .where(ExecutionEvent.trade_id.in_(trade_ids))
                .order_by(ExecutionEvent.event_time_ms.asc(), ExecutionEvent.id.asc())
                .limit(10000)
            ).all()
            for row in rows:
                events_by_trade[row.trade_id].append({
                    "id": row.id, "source_event_id": row.source_event_id,
                    "sequence_no": row.sequence_no, "event_type": row.event_type,
                    "event_time_ms": row.event_time_ms, "pnl": row.pnl, "fee": row.fee,
                })
        finally:
            db.close()
    return portfolio, trades, events_by_trade

class _Phase22PreflightRequest(_Phase2125BaseModel):
    side: str = _Phase2125Field(pattern="^(long|short)$")
    quantity: float = _Phase2125Field(gt=0, le=1_000_000_000)
    entry: float = _Phase2125Field(gt=0)
    stop_loss: float = _Phase2125Field(gt=0)


class _Phase23AdaptiveRiskRequest(_Phase2125BaseModel):
    baseline_risk_pct: float = _Phase2125Field(default=0.25, gt=0, le=5)
    max_risk_pct: float = _Phase2125Field(default=0.5, gt=0, le=5)
    volatility_multiple: float = _Phase2125Field(default=1.0, gt=0, le=20)
    drawdown_pct: float = _Phase2125Field(default=0.0, ge=0, le=100)
    market_regime: str = "unknown"


@router.get("/portfolios/{portfolio_id}/paper-control")
def api_phase21_paper_control(portfolio_id: str, limit: int = 500, user=Depends(current_user)):
    if not 1 <= limit <= 500:
        raise HTTPException(status_code=422, detail="limit must be between 1 and 500")
    try:
        portfolio, trades, events = _phase2125_context(user["id"], portfolio_id, limit)
        result = _phase21_paper_control(trades=trades, events_by_trade=events)
        result.update({"portfolio_id": portfolio_id, "portfolio_name": portfolio["name"],
                       "trades_returned": len(trades), "truncated": len(trades) >= limit})
        return result
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.post("/portfolios/{portfolio_id}/execution-preflight")
def api_phase22_execution_preflight(portfolio_id: str, payload: _Phase22PreflightRequest,
                                    user=Depends(current_user)):
    try:
        portfolio, trades, _ = _phase2125_context(user["id"], portfolio_id, 500)
        result = _phase22_preflight(portfolio=portfolio, trades=trades, side=payload.side,
                                    quantity=payload.quantity, entry=payload.entry,
                                    stop_loss=payload.stop_loss)
        result["portfolio_id"] = portfolio_id
        return result
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.post("/portfolios/{portfolio_id}/adaptive-risk")
def api_phase23_adaptive_risk(portfolio_id: str, payload: _Phase23AdaptiveRiskRequest,
                              user=Depends(current_user)):
    try:
        portfolio = get_portfolio(user["id"], portfolio_id)
        result = _phase23_adaptive_risk(
            baseline_risk_pct=payload.baseline_risk_pct,
            max_risk_pct=min(payload.max_risk_pct, float(portfolio["max_trade_risk_pct"])),
            volatility_multiple=payload.volatility_multiple,
            drawdown_pct=payload.drawdown_pct,
            market_regime=payload.market_regime,
        )
        result["portfolio_id"] = portfolio_id
        result["portfolio_max_trade_risk_pct"] = portfolio["max_trade_risk_pct"]
        return result
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.get("/portfolios/{portfolio_id}/intelligence-alerts")
def api_phase24_intelligence_alerts(portfolio_id: str, limit: int = 500,
                                    stale_after_seconds: int = 180, user=Depends(current_user)):
    if not 1 <= limit <= 500 or not 1 <= stale_after_seconds <= 86400:
        raise HTTPException(status_code=422, detail="Invalid limit or stale_after_seconds")
    try:
        portfolio, trades, _ = _phase2125_context(user["id"], portfolio_id, limit)
        result = _phase24_alerts(trades=trades,
                                 now_ms=int(_now().timestamp() * 1000),
                                 stale_after_seconds=stale_after_seconds)
        result.update({"portfolio_id": portfolio_id, "portfolio_name": portfolio["name"]})
        return result
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.get("/portfolios/{portfolio_id}/reliability")
def api_phase25_reliability(portfolio_id: str, limit: int = 500, user=Depends(current_user)):
    if not 1 <= limit <= 500:
        raise HTTPException(status_code=422, detail="limit must be between 1 and 500")
    database_ok = False
    try:
        portfolio, trades, events = _phase2125_context(user["id"], portfolio_id, limit)
        db = _session()
        try:
            db.execute(select(1))
            database_ok = True
        finally:
            db.close()
        control = _phase21_paper_control(trades=trades, events_by_trade=events)
        alerts = _phase24_alerts(trades=trades, now_ms=int(_now().timestamp() * 1000))
        result = _phase25_reliability(database_probe_ok=database_ok, trades=trades,
                                      paper_control=control, alerts=alerts)
        result.update({"portfolio_id": portfolio_id, "portfolio_name": portfolio["name"],
                       "trades_returned": len(trades), "truncated": len(trades) >= limit})
        return result
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

# ===== END TRADF PHASES 21-25 =====

