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
    PaperOrder, AuditEvent, BacktestRun,
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
    open_risk = sum(float(o.risk_cash) for o in open_orders)
    equity = float(p.initial_equity)
    return {
        "id": p.id, "name": p.name, "base_currency": p.base_currency,
        "initial_equity": equity, "realized_pnl": round(realized, 8),
        "cash_equity": round(equity + realized, 8),
        "open_positions": len(open_orders), "open_risk_cash": round(open_risk, 8),
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


class ForwardTestStartRequest(BaseModel):
    portfolio_id: str
    account_id: str
    symbols: list[str] = Field(min_length=1, max_length=50)
    risk_per_trade_pct: float = Field(default=0.5, gt=0, le=5)
    min_quality_score: int = Field(default=70, ge=0, le=100)
    commission_pct: float = Field(default=0.04, ge=0, le=1)
    slippage_bps: float = Field(default=2.0, ge=0, le=500)
    include_existing_signals: bool = False


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
