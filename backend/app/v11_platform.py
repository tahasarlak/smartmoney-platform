from __future__ import annotations

import hashlib
import hmac
import json
import math
import os
import secrets
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field, field_validator


DB_DEFAULT = Path(__file__).resolve().parents[1] / "data" / "smartmoney_v11.sqlite3"
TOKEN_TTL_HOURS = 12
PBKDF2_ITERATIONS = 310_000


def _db_path() -> Path:
    raw = os.getenv("SMARTMONEY_V11_DB")
    path = Path(raw).expanduser() if raw else DB_DEFAULT
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _connect() -> sqlite3.Connection:
    con = sqlite3.connect(_db_path(), timeout=15)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA busy_timeout=15000")
    return con


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None = None) -> str:
    return (value or _now()).isoformat()


def init_v11_db() -> None:
    with _connect() as con:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS v11_users (
          id TEXT PRIMARY KEY,
          email TEXT NOT NULL UNIQUE COLLATE NOCASE,
          password_hash TEXT NOT NULL,
          is_active INTEGER NOT NULL DEFAULT 1,
          created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS v11_sessions (
          token_hash TEXT PRIMARY KEY,
          user_id TEXT NOT NULL REFERENCES v11_users(id) ON DELETE CASCADE,
          expires_at TEXT NOT NULL,
          created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_v11_sessions_user ON v11_sessions(user_id);
        CREATE TABLE IF NOT EXISTS v11_portfolios (
          id TEXT PRIMARY KEY,
          user_id TEXT NOT NULL REFERENCES v11_users(id) ON DELETE CASCADE,
          name TEXT NOT NULL,
          base_currency TEXT NOT NULL DEFAULT 'USDT',
          initial_equity REAL NOT NULL CHECK(initial_equity > 0),
          max_open_trades INTEGER NOT NULL DEFAULT 3 CHECK(max_open_trades BETWEEN 1 AND 100),
          max_portfolio_risk_pct REAL NOT NULL DEFAULT 3 CHECK(max_portfolio_risk_pct BETWEEN 0 AND 100),
          max_trade_risk_pct REAL NOT NULL DEFAULT 1 CHECK(max_trade_risk_pct BETWEEN 0 AND 100),
          created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_v11_portfolios_user ON v11_portfolios(user_id);
        CREATE TABLE IF NOT EXISTS v11_broker_accounts (
          id TEXT PRIMARY KEY,
          user_id TEXT NOT NULL REFERENCES v11_users(id) ON DELETE CASCADE,
          portfolio_id TEXT NOT NULL REFERENCES v11_portfolios(id) ON DELETE CASCADE,
          broker TEXT NOT NULL CHECK(broker IN ('binance','mt5')),
          mode TEXT NOT NULL CHECK(mode = 'paper'),
          label TEXT NOT NULL,
          created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_v11_accounts_portfolio ON v11_broker_accounts(portfolio_id);
        CREATE TABLE IF NOT EXISTS v11_paper_orders (
          id TEXT PRIMARY KEY,
          user_id TEXT NOT NULL REFERENCES v11_users(id) ON DELETE CASCADE,
          portfolio_id TEXT NOT NULL REFERENCES v11_portfolios(id) ON DELETE CASCADE,
          account_id TEXT NOT NULL REFERENCES v11_broker_accounts(id) ON DELETE CASCADE,
          broker TEXT NOT NULL CHECK(broker IN ('binance','mt5')),
          symbol TEXT NOT NULL,
          side TEXT NOT NULL CHECK(side IN ('long','short')),
          quantity REAL NOT NULL CHECK(quantity > 0),
          entry_price REAL NOT NULL CHECK(entry_price > 0),
          stop_loss REAL NOT NULL CHECK(stop_loss > 0),
          take_profit REAL NOT NULL CHECK(take_profit > 0),
          risk_cash REAL NOT NULL CHECK(risk_cash >= 0),
          status TEXT NOT NULL CHECK(status IN ('open','closed')),
          exit_price REAL,
          realized_pnl REAL,
          created_at TEXT NOT NULL,
          closed_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_v11_orders_portfolio ON v11_paper_orders(portfolio_id, status);
        CREATE INDEX IF NOT EXISTS idx_v11_orders_user ON v11_paper_orders(user_id, created_at DESC);
        CREATE TABLE IF NOT EXISTS v11_audit_events (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          user_id TEXT NOT NULL REFERENCES v11_users(id) ON DELETE CASCADE,
          portfolio_id TEXT,
          event_type TEXT NOT NULL,
          entity_id TEXT,
          details_json TEXT NOT NULL,
          created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_v11_audit_user ON v11_audit_events(user_id, created_at DESC);
        CREATE TABLE IF NOT EXISTS v11_backtest_runs (
          id TEXT PRIMARY KEY,
          user_id TEXT NOT NULL REFERENCES v11_users(id) ON DELETE CASCADE,
          portfolio_id TEXT NOT NULL REFERENCES v11_portfolios(id) ON DELETE CASCADE,
          result_json TEXT NOT NULL,
          created_at TEXT NOT NULL
        );
        """)


def _hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt.hex()}${digest.hex()}"


def _verify_password(password: str, encoded: str) -> bool:
    try:
        scheme, rounds, salt_hex, digest_hex = encoded.split("$", 3)
        if scheme != "pbkdf2_sha256":
            return False
        actual = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt_hex), int(rounds)).hex()
        return hmac.compare_digest(actual, digest_hex)
    except (ValueError, TypeError):
        return False


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def register_user(email: str, password: str) -> dict[str, Any]:
    email = email.strip().lower()
    if len(password) < 10:
        raise ValueError("Password must contain at least 10 characters")
    user_id = str(uuid.uuid4())
    portfolio_id = str(uuid.uuid4())
    now = _iso()
    try:
        with _connect() as con:
            con.execute("INSERT INTO v11_users(id,email,password_hash,created_at) VALUES(?,?,?,?)",
                        (user_id, email, _hash_password(password), now))
            con.execute("""INSERT INTO v11_portfolios
                (id,user_id,name,base_currency,initial_equity,max_open_trades,max_portfolio_risk_pct,max_trade_risk_pct,created_at)
                VALUES(?,?,?,?,?,?,?,?,?)""",
                (portfolio_id, user_id, "Main Portfolio", "USDT", 10_000.0, 3, 3.0, 1.0, now))
            con.execute("INSERT INTO v11_audit_events(user_id,portfolio_id,event_type,details_json,created_at) VALUES(?,?,?,?,?)",
                        (user_id, portfolio_id, "USER_REGISTERED", "{}", now))
    except sqlite3.IntegrityError as exc:
        raise ValueError("An account with this email already exists") from exc
    return {"id": user_id, "email": email, "created_at": now, "default_portfolio_id": portfolio_id}


def create_session(email: str, password: str) -> dict[str, Any]:
    with _connect() as con:
        row = con.execute("SELECT * FROM v11_users WHERE email=? COLLATE NOCASE", (email.strip(),)).fetchone()
    if row is None or not row["is_active"] or not _verify_password(password, row["password_hash"]):
        raise ValueError("Invalid email or password")
    token = secrets.token_urlsafe(40)
    expires = _now() + timedelta(hours=TOKEN_TTL_HOURS)
    with _connect() as con:
        con.execute("INSERT INTO v11_sessions(token_hash,user_id,expires_at,created_at) VALUES(?,?,?,?)",
                    (_token_hash(token), row["id"], _iso(expires), _iso()))
    return {"access_token": token, "token_type": "bearer", "expires_at": _iso(expires),
            "user": {"id": row["id"], "email": row["email"]}}


def revoke_session(token: str | None) -> None:
    if not token:
        return
    with _connect() as con:
        con.execute("DELETE FROM v11_sessions WHERE token_hash=?", (_token_hash(token),))


def authenticate_token(token: str | None) -> dict[str, str]:
    if not token:
        raise HTTPException(status_code=401, detail="Bearer token required")
    with _connect() as con:
        row = con.execute("""SELECT u.id,u.email,s.expires_at FROM v11_sessions s
            JOIN v11_users u ON u.id=s.user_id
            WHERE s.token_hash=? AND u.is_active=1""", (_token_hash(token),)).fetchone()
    if row is None or row["expires_at"] <= _iso():
        raise HTTPException(status_code=401, detail="Session is invalid or expired")
    return {"id": row["id"], "email": row["email"]}


def _audit(con: sqlite3.Connection, user_id: str, event_type: str,
           portfolio_id: str | None = None, entity_id: str | None = None,
           details: dict[str, Any] | None = None) -> None:
    con.execute("""INSERT INTO v11_audit_events
        (user_id,portfolio_id,event_type,entity_id,details_json,created_at)
        VALUES(?,?,?,?,?,?)""",
        (user_id, portfolio_id, event_type, entity_id,
         json.dumps(details or {}, separators=(",", ":"), allow_nan=False), _iso()))


def create_portfolio(user_id: str, name: str, initial_equity: float,
                     max_open_trades: int = 3, max_portfolio_risk_pct: float = 3.0,
                     max_trade_risk_pct: float = 1.0, base_currency: str = "USDT") -> dict[str, Any]:
    if not name.strip() or len(name) > 80:
        raise ValueError("Portfolio name must contain 1..80 characters")
    values = (initial_equity, max_portfolio_risk_pct, max_trade_risk_pct)
    if not all(math.isfinite(v) for v in values) or initial_equity <= 0 or not 0 <= max_portfolio_risk_pct <= 100 or not 0 <= max_trade_risk_pct <= 100:
        raise ValueError("Invalid portfolio equity or risk limits")
    if not 1 <= max_open_trades <= 100:
        raise ValueError("max_open_trades must be between 1 and 100")
    pid = str(uuid.uuid4())
    now = _iso()
    with _connect() as con:
        con.execute("""INSERT INTO v11_portfolios
            (id,user_id,name,base_currency,initial_equity,max_open_trades,max_portfolio_risk_pct,max_trade_risk_pct,created_at)
            VALUES(?,?,?,?,?,?,?,?,?)""",
            (pid,user_id,name.strip(),base_currency.upper(),initial_equity,max_open_trades,
             max_portfolio_risk_pct,max_trade_risk_pct,now))
        _audit(con,user_id,"PORTFOLIO_CREATED",pid,pid,{"name":name.strip()})
    return get_portfolio(user_id, pid)


def _owned_portfolio(con: sqlite3.Connection, user_id: str, portfolio_id: str):
    row = con.execute("SELECT * FROM v11_portfolios WHERE id=? AND user_id=?", (portfolio_id,user_id)).fetchone()
    if row is None:
        raise LookupError("Portfolio not found")
    return row


def get_portfolio(user_id: str, portfolio_id: str) -> dict[str, Any]:
    with _connect() as con:
        p = _owned_portfolio(con,user_id,portfolio_id)
        accounts = con.execute("SELECT id,broker,mode,label,created_at FROM v11_broker_accounts WHERE portfolio_id=? AND user_id=? ORDER BY created_at",(portfolio_id,user_id)).fetchall()
        orders = con.execute("SELECT * FROM v11_paper_orders WHERE portfolio_id=? AND user_id=?",(portfolio_id,user_id)).fetchall()
    realized = sum(float(o["realized_pnl"] or 0) for o in orders if o["status"] == "closed")
    open_orders = [o for o in orders if o["status"] == "open"]
    open_risk = sum(float(o["risk_cash"]) for o in open_orders)
    return {
        "id":p["id"],"name":p["name"],"base_currency":p["base_currency"],
        "initial_equity":p["initial_equity"],"realized_pnl":round(realized,8),
        "cash_equity":round(float(p["initial_equity"])+realized,8),
        "open_positions":len(open_orders),"open_risk_cash":round(open_risk,8),
        "open_risk_pct":round(open_risk/float(p["initial_equity"])*100,6),
        "max_open_trades":p["max_open_trades"],"max_portfolio_risk_pct":p["max_portfolio_risk_pct"],
        "max_trade_risk_pct":p["max_trade_risk_pct"],"accounts":[dict(a) for a in accounts],"created_at":p["created_at"]
    }


def list_portfolios(user_id: str) -> list[dict[str, Any]]:
    with _connect() as con:
        rows = con.execute("SELECT id FROM v11_portfolios WHERE user_id=? ORDER BY created_at",(user_id,)).fetchall()
    return [get_portfolio(user_id,r["id"]) for r in rows]


def create_broker_account(user_id: str, portfolio_id: str, broker: str, label: str) -> dict[str, Any]:
    broker = broker.lower()
    if broker not in ("binance", "mt5"):
        raise ValueError("broker must be binance or mt5")
    if not label.strip() or len(label) > 80:
        raise ValueError("Account label must contain 1..80 characters")
    aid = str(uuid.uuid4()); now = _iso()
    with _connect() as con:
        _owned_portfolio(con,user_id,portfolio_id)
        con.execute("""INSERT INTO v11_broker_accounts(id,user_id,portfolio_id,broker,mode,label,created_at)
            VALUES(?,?,?,?,?,?,?)""",(aid,user_id,portfolio_id,broker,"paper",label.strip(),now))
        _audit(con,user_id,"PAPER_ACCOUNT_CREATED",portfolio_id,aid,{"broker":broker,"mode":"paper"})
    return {"id":aid,"portfolio_id":portfolio_id,"broker":broker,"mode":"paper","label":label.strip(),"created_at":now}


def list_broker_accounts(user_id: str, portfolio_id: str) -> list[dict[str, Any]]:
    with _connect() as con:
        _owned_portfolio(con,user_id,portfolio_id)
        rows=con.execute("SELECT id,portfolio_id,broker,mode,label,created_at FROM v11_broker_accounts WHERE user_id=? AND portfolio_id=? ORDER BY created_at",(user_id,portfolio_id)).fetchall()
    return [dict(r) for r in rows]


def create_paper_order(user_id: str, account_id: str, symbol: str, side: str,
                       quantity: float, reference_price: float, stop_loss: float,
                       take_profit: float) -> dict[str, Any]:
    symbol = symbol.strip().upper(); side = side.lower()
    if not symbol or len(symbol) > 30 or not symbol.replace("_", "").isalnum():
        raise ValueError("Invalid symbol")
    if side not in ("long", "short"):
        raise ValueError("side must be long or short")
    vals=(quantity,reference_price,stop_loss,take_profit)
    if not all(math.isfinite(v) and v > 0 for v in vals):
        raise ValueError("Quantity and all prices must be finite and positive")
    if side == "long" and not stop_loss < reference_price < take_profit:
        raise ValueError("For long orders require stop_loss < reference_price < take_profit")
    if side == "short" and not take_profit < reference_price < stop_loss:
        raise ValueError("For short orders require take_profit < reference_price < stop_loss")
    oid=str(uuid.uuid4()); now=_iso()
    with _connect() as con:
        account=con.execute("""SELECT a.*,p.initial_equity,p.max_open_trades,p.max_portfolio_risk_pct,p.max_trade_risk_pct
            FROM v11_broker_accounts a JOIN v11_portfolios p ON p.id=a.portfolio_id
            WHERE a.id=? AND a.user_id=? AND p.user_id=?""",(account_id,user_id,user_id)).fetchone()
        if account is None:
            raise LookupError("Broker account not found")
        open_rows=con.execute("SELECT risk_cash FROM v11_paper_orders WHERE portfolio_id=? AND user_id=? AND status='open'",(account["portfolio_id"],user_id)).fetchall()
        if len(open_rows) >= int(account["max_open_trades"]):
            raise ValueError("Portfolio max_open_trades limit reached")
        risk_cash=abs(reference_price-stop_loss)*quantity
        equity=float(account["initial_equity"])
        realized=con.execute("SELECT COALESCE(SUM(realized_pnl),0) AS pnl FROM v11_paper_orders WHERE portfolio_id=? AND user_id=? AND status='closed'",(account["portfolio_id"],user_id)).fetchone()["pnl"]
        equity += float(realized)
        if equity <= 0:
            raise ValueError("Portfolio equity is not positive")
        if risk_cash/equity*100 > float(account["max_trade_risk_pct"]):
            raise ValueError("Per-trade risk limit exceeded")
        total_open_risk=sum(float(r["risk_cash"]) for r in open_rows)
        if (total_open_risk+risk_cash)/equity*100 > float(account["max_portfolio_risk_pct"]):
            raise ValueError("Portfolio aggregate open-risk limit exceeded")
        con.execute("""INSERT INTO v11_paper_orders
            (id,user_id,portfolio_id,account_id,broker,symbol,side,quantity,entry_price,stop_loss,take_profit,risk_cash,status,created_at)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (oid,user_id,account["portfolio_id"],account_id,account["broker"],symbol,side,quantity,reference_price,stop_loss,take_profit,risk_cash,"open",now))
        _audit(con,user_id,"PAPER_ORDER_OPENED",account["portfolio_id"],oid,{"broker":account["broker"],"symbol":symbol,"side":side,"quantity":quantity,"reference_price":reference_price})
    return get_order(user_id,oid)


def get_order(user_id: str, order_id: str) -> dict[str, Any]:
    with _connect() as con:
        row=con.execute("SELECT * FROM v11_paper_orders WHERE id=? AND user_id=?",(order_id,user_id)).fetchone()
    if row is None: raise LookupError("Order not found")
    return dict(row)


def list_orders(user_id: str, portfolio_id: str, status: str | None = None) -> list[dict[str, Any]]:
    with _connect() as con:
        _owned_portfolio(con,user_id,portfolio_id)
        if status:
            rows=con.execute("SELECT * FROM v11_paper_orders WHERE user_id=? AND portfolio_id=? AND status=? ORDER BY created_at DESC",(user_id,portfolio_id,status.lower())).fetchall()
        else:
            rows=con.execute("SELECT * FROM v11_paper_orders WHERE user_id=? AND portfolio_id=? ORDER BY created_at DESC",(user_id,portfolio_id)).fetchall()
    return [dict(r) for r in rows]


def close_paper_order(user_id: str, order_id: str, exit_price: float) -> dict[str, Any]:
    if not math.isfinite(exit_price) or exit_price <= 0:
        raise ValueError("exit_price must be finite and positive")
    with _connect() as con:
        row=con.execute("SELECT * FROM v11_paper_orders WHERE id=? AND user_id=?",(order_id,user_id)).fetchone()
        if row is None: raise LookupError("Order not found")
        if row["status"] != "open": raise ValueError("Order is already closed")
        side=1 if row["side"]=="long" else -1
        pnl=(exit_price-float(row["entry_price"]))*float(row["quantity"])*side
        now=_iso()
        con.execute("UPDATE v11_paper_orders SET status='closed',exit_price=?,realized_pnl=?,closed_at=? WHERE id=? AND user_id=?",
                    (exit_price,pnl,now,order_id,user_id))
        _audit(con,user_id,"PAPER_ORDER_CLOSED",row["portfolio_id"],order_id,{"exit_price":exit_price,"realized_pnl":pnl})
    return get_order(user_id,order_id)


def save_backtest_run(user_id: str, portfolio_id: str, result: dict[str, Any]) -> dict[str, Any]:
    run_id = str(uuid.uuid4()); now = _iso()
    payload = json.dumps(result, separators=(",", ":"), allow_nan=False)
    with _connect() as con:
        _owned_portfolio(con, user_id, portfolio_id)
        con.execute("INSERT INTO v11_backtest_runs(id,user_id,portfolio_id,result_json,created_at) VALUES(?,?,?,?,?)",
                    (run_id, user_id, portfolio_id, payload, now))
        _audit(con, user_id, "SHARED_BACKTEST_COMPLETED", portfolio_id, run_id,
               {"trade_count": result.get("trade_count"), "net_pnl": result.get("net_pnl")})
    return {"id": run_id, "portfolio_id": portfolio_id, "created_at": now, "result": result}


def list_backtest_runs(user_id: str, portfolio_id: str, limit: int = 20) -> list[dict[str, Any]]:
    with _connect() as con:
        _owned_portfolio(con, user_id, portfolio_id)
        rows = con.execute("SELECT id,created_at,result_json FROM v11_backtest_runs WHERE user_id=? AND portfolio_id=? ORDER BY created_at DESC LIMIT ?",
                           (user_id, portfolio_id, limit)).fetchall()
    return [{"id": r["id"], "created_at": r["created_at"], "result": json.loads(r["result_json"])} for r in rows]


def list_audit_events(user_id: str, limit: int = 100) -> list[dict[str, Any]]:
    with _connect() as con:
        rows=con.execute("SELECT id,portfolio_id,event_type,entity_id,details_json,created_at FROM v11_audit_events WHERE user_id=? ORDER BY id DESC LIMIT ?",(user_id,limit)).fetchall()
    return [{**dict(r),"details":json.loads(r["details_json"])} for r in rows]


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


def current_user(authorization: str | None = Header(default=None)) -> dict[str, str]:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Bearer token required")
    return authenticate_token(authorization.split(" ",1)[1].strip())


router = APIRouter(prefix="/api/v1/v11", tags=["SmartMoney V11"])


@router.post("/auth/register", status_code=201)
def api_register(payload: RegisterRequest):
    try: return register_user(payload.email,payload.password)
    except ValueError as exc: raise HTTPException(status_code=409,detail=str(exc))


@router.post("/auth/login")
def api_login(payload: LoginRequest):
    try: return create_session(payload.email,payload.password)
    except ValueError as exc: raise HTTPException(status_code=401,detail=str(exc))


@router.get("/auth/me")
def api_me(user: dict[str,str] = Depends(current_user)):
    return user


@router.post("/auth/logout")
def api_logout(authorization: str | None = Header(default=None), user=Depends(current_user)):
    token = authorization.split(" ", 1)[1].strip() if authorization else None
    revoke_session(token)
    return {"revoked": True}


@router.get("/system/readiness")
def api_readiness():
    return {
        "version":"11.0.0","mode":"paper_only","live_execution_enabled":False,
        "phases":{
            "market_analysis":{"status":"available","details":"Existing SMC, MTF and V8 research engines retained"},
            "shared_portfolio_backtesting":{"status":"available","details":"V10 shared-equity OHLC replay retained; broker margin model not included"},
            "multi_user_auth":{"status":"available","details":"Email/password, PBKDF2 hashes, opaque expiring bearer sessions"},
            "tenant_paper_accounts":{"status":"available","details":"Per-user portfolios, broker-labelled paper accounts and tenant-scoped orders"},
            "binance":{"status":"paper_simulation","details":"Public market-data adapter exists; orders are simulated only"},
            "mt5":{"status":"paper_simulation","details":"Broker-labelled paper accounts; terminal/EA bridge is not configured"},
            "walk_forward_monte_carlo":{"status":"not_implemented","details":"Requires strategy-generated historical signals and validation suite"},
            "production_deployment":{"status":"partial","details":"Docker foundation exists; TLS, secrets vault, Redis workers and production database migration require deployment-specific work"}
        },
        "execution_allowed":False
    }


@router.get("/brokers")
def api_brokers():
    return {"brokers":[
        {"id":"binance","name":"Binance","market_data":"public_api","paper_execution":True,"live_execution":False,"status":"available_for_paper"},
        {"id":"mt5","name":"MetaTrader 5","market_data":"bridge_not_configured","paper_execution":True,"live_execution":False,"status":"paper_simulator_only","bridge_required_for_terminal_data":True}
    ],"execution_allowed":False}


@router.post("/portfolios", status_code=201)
def api_create_portfolio(payload: PortfolioRequest,user=Depends(current_user)):
    try: return create_portfolio(user["id"],payload.name,payload.initial_equity,payload.max_open_trades,payload.max_portfolio_risk_pct,payload.max_trade_risk_pct,payload.base_currency)
    except ValueError as exc: raise HTTPException(status_code=422,detail=str(exc))


@router.get("/portfolios")
def api_list_portfolios(user=Depends(current_user)):
    return {"items":list_portfolios(user["id"])}


@router.post("/accounts", status_code=201)
def api_create_account(payload: BrokerAccountRequest,user=Depends(current_user)):
    try: return create_broker_account(user["id"],payload.portfolio_id,payload.broker,payload.label)
    except LookupError as exc: raise HTTPException(status_code=404,detail=str(exc))
    except ValueError as exc: raise HTTPException(status_code=422,detail=str(exc))


@router.get("/accounts")
def api_list_accounts(portfolio_id: str,user=Depends(current_user)):
    try: return {"items":list_broker_accounts(user["id"],portfolio_id)}
    except LookupError as exc: raise HTTPException(status_code=404,detail=str(exc))


@router.post("/paper/orders", status_code=201)
def api_create_order(payload: PaperOrderRequest,user=Depends(current_user)):
    try: return create_paper_order(user["id"],payload.account_id,payload.symbol,payload.side,payload.quantity,payload.reference_price,payload.stop_loss,payload.take_profit)
    except LookupError as exc: raise HTTPException(status_code=404,detail=str(exc))
    except ValueError as exc: raise HTTPException(status_code=422,detail=str(exc))


@router.get("/paper/orders")
def api_list_orders(portfolio_id: str,status: str|None=None,user=Depends(current_user)):
    if status and status.lower() not in ("open","closed"): raise HTTPException(status_code=422,detail="status must be open or closed")
    try: return {"items":list_orders(user["id"],portfolio_id,status)}
    except LookupError as exc: raise HTTPException(status_code=404,detail=str(exc))


@router.post("/paper/orders/{order_id}/close")
def api_close_order(order_id: str,payload: ClosePaperOrderRequest,user=Depends(current_user)):
    try: return close_paper_order(user["id"],order_id,payload.exit_price)
    except LookupError as exc: raise HTTPException(status_code=404,detail=str(exc))
    except ValueError as exc: raise HTTPException(status_code=422,detail=str(exc))


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
    except LookupError as exc: raise HTTPException(status_code=404, detail=str(exc))
    except (KeyError, TypeError, ValueError) as exc: raise HTTPException(status_code=422, detail=str(exc))


@router.get("/backtests/shared")
def api_list_shared_backtests(portfolio_id: str, limit: int = 20, user=Depends(current_user)):
    if not 1 <= limit <= 100: raise HTTPException(status_code=422, detail="limit must be 1..100")
    try: return {"items": list_backtest_runs(user["id"], portfolio_id, limit)}
    except LookupError as exc: raise HTTPException(status_code=404, detail=str(exc))


@router.get("/audit")
def api_audit(limit: int=100,user=Depends(current_user)):
    if not 1 <= limit <= 500: raise HTTPException(status_code=422,detail="limit must be 1..500")
    return {"items":list_audit_events(user["id"],limit)}


@router.get("/portfolios/{portfolio_id}")
def api_get_portfolio(portfolio_id: str,user=Depends(current_user)):
    try: return get_portfolio(user["id"],portfolio_id)
    except LookupError as exc: raise HTTPException(status_code=404,detail=str(exc))
