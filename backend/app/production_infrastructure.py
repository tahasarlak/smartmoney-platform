from __future__ import annotations
import asyncio
import hashlib
import json
import os
import re
import socket
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field, SecretStr, field_validator
from sqlalchemy import select, func, text
from sqlalchemy.orm import Session

from .database import get_session_factory
from .db_models import User, Session as LoginSession, Portfolio, ExecutionTrade, AuditEvent
from .production_models import ExchangeCredential, ExchangeOrder, UserKillSwitch, GlobalKillSwitch, SchedulerJob, PaperBurninSample
from .production_security import encrypt_secret, decrypt_secret, key_fingerprint, vault_ready, CredentialVaultError
from .production_exchange import BinanceSpotTestnet, ExchangeTestnetError

router = APIRouter(prefix="/api/v1/v11/production", tags=["TRADF Production Safety"])
def _now(): return datetime.now(timezone.utc)
def _db(): return get_session_factory()()
def _token_hash(token: str) -> str: return hashlib.sha256(token.encode()).hexdigest()

def _acquire_execution_locks(db: Session,user_id: str | None=None):
    """Serialize order submission against global and per-user kill-switch changes.

    These transaction-scoped advisory locks are PostgreSQL-specific by design;
    this application uses Neon PostgreSQL in production.
    """
    db.execute(text("SELECT pg_advisory_xact_lock(:namespace, :lock_id)"),
        {"namespace":1414677316,"lock_id":0})
    if user_id is not None:
        raw=hashlib.sha256(user_id.encode()).digest()[:4]
        lock_id=int.from_bytes(raw,byteorder="big",signed=True)
        if lock_id==0: lock_id=1
        db.execute(text("SELECT pg_advisory_xact_lock(:namespace, :lock_id)"),
            {"namespace":1414677316,"lock_id":lock_id})

def _audit_security_event(db: Session,user_id: str,event_type: str,portfolio_id: str | None=None,
                          entity_id: str | None=None,details: dict[str,Any] | None=None):
    # Never put API keys, secrets, signatures, access tokens, or request bodies in audit details.
    db.add(AuditEvent(user_id=user_id,portfolio_id=portfolio_id,event_type=event_type,
        entity_id=entity_id,details_json=details or {},created_at=_now()))

def current_user(authorization: str | None = Header(default=None)):
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Bearer token required")
    token=authorization.split(" ",1)[1].strip()
    db=_db()
    try:
        row=db.execute(select(User.id,User.email,LoginSession.expires_at)
            .join(LoginSession,LoginSession.user_id==User.id)
            .where(LoginSession.token_hash==_token_hash(token),User.is_active.is_(True))).first()
        if row is None or (row.expires_at.replace(tzinfo=timezone.utc) if row.expires_at.tzinfo is None else row.expires_at) <= _now():
            raise HTTPException(status_code=401,detail="Session is invalid or expired")
        return {"id":row.id,"email":row.email}
    finally: db.close()

def _owned_portfolio(db: Session,user_id: str,portfolio_id: str):
    p=db.scalar(select(Portfolio).where(Portfolio.id==portfolio_id,Portfolio.user_id==user_id))
    if p is None: raise HTTPException(status_code=404,detail="Portfolio not found")
    return p

def _credential(db: Session,user_id: str,credential_id: str):
    c=db.scalar(select(ExchangeCredential).where(ExchangeCredential.id==credential_id,
        ExchangeCredential.user_id==user_id,ExchangeCredential.status=="active"))
    if c is None: raise HTTPException(status_code=404,detail="Active testnet credential not found")
    return c

def _adapter(c: ExchangeCredential):
    try:
        return BinanceSpotTestnet(decrypt_secret(c.encrypted_api_key),decrypt_secret(c.encrypted_api_secret))
    except CredentialVaultError as exc:
        raise HTTPException(status_code=503,detail=str(exc))

def _global_kill_enabled(db: Session | None = None) -> bool:
    env_enabled = os.getenv("TRADF_GLOBAL_KILL_SWITCH","true").strip().lower() in {"1","true","yes","on"}
    if env_enabled:
        return True
    if db is None:
        return True
    row = db.get(GlobalKillSwitch, 1)
    return True if row is None else bool(row.enabled)

def _testnet_orders_enabled() -> bool:
    return os.getenv("TRADF_TESTNET_TRADING_ENABLED","false").strip().lower() in {"1","true","yes","on"}

def _user_kill_enabled(db: Session,user_id: str) -> bool:
    row=db.get(UserKillSwitch,user_id)
    # Fail closed: no explicit resume means the kill switch is on.
    return row is None or bool(row.enabled)

def _execution_guard(db: Session,user_id: str):
    if _global_kill_enabled(db): raise HTTPException(status_code=423,detail="Global emergency kill switch is enabled")
    if _user_kill_enabled(db,user_id): raise HTTPException(status_code=423,detail="User kill switch is enabled; explicit resume required")
    if not _testnet_orders_enabled():
        raise HTTPException(status_code=423,detail="Testnet order placement is disabled by deployment configuration")
    if os.getenv("LIVE_TRADING_ENABLED","false").strip().lower() in {"1","true","yes","on"}:
        raise HTTPException(status_code=423,detail="Live trading configuration is forbidden by this testnet-only module")

class CredentialCreate(BaseModel):
    portfolio_id: str
    label: str = Field(min_length=1,max_length=80)
    api_key: SecretStr = Field(min_length=8,max_length=256)
    api_secret: SecretStr = Field(min_length=8,max_length=256)
    acknowledge_testnet_only: bool

class LimitOrderCreate(BaseModel):
    credential_id: str
    portfolio_id: str
    symbol: str = Field(pattern=r"^[A-Za-z0-9]{5,30}$")
    side: str = Field(pattern=r"^(BUY|SELL)$")
    quantity: str = Field(min_length=1,max_length=40)
    price: str = Field(min_length=1,max_length=40)
    client_request_id: str = Field(min_length=8,max_length=80)
    confirm_testnet_only: bool

    @field_validator("quantity","price")
    @classmethod
    def validate_positive_decimal(cls,value: str) -> str:
        try:
            number=Decimal(value)
        except (InvalidOperation,ValueError):
            raise ValueError("quantity and price must be valid decimal strings")
        if not number.is_finite() or number<=0:
            raise ValueError("quantity and price must be finite and positive")
        return format(number.normalize(),"f")


def _require_admin_control(candidate: str | None):
    expected=os.getenv("TRADF_ADMIN_CONTROL_TOKEN","").strip()
    if not expected:
        raise HTTPException(status_code=503,detail="TRADF_ADMIN_CONTROL_TOKEN is not configured")
    if not candidate or not __import__("hmac").compare_digest(candidate,expected):
        raise HTTPException(status_code=403,detail="Admin control token is invalid")

async def _cancel_all_open_testnet_orders(db: Session):
    orders=db.scalars(select(ExchangeOrder).where(
        ExchangeOrder.status.in_(["NEW","PARTIALLY_FILLED","PENDING_CANCEL","SUBMITTING","UNKNOWN"]))).all()
    cancelled=[];failed=[]
    for order in orders:
        credential=db.scalar(select(ExchangeCredential).where(
            ExchangeCredential.id==order.credential_id,ExchangeCredential.status=="active"))
        if credential is None:
            failed.append(order.id);continue
        try:
            result=await _adapter(credential).cancel_order(symbol=order.symbol,
                order_id=order.exchange_order_id,client_order_id=None if order.exchange_order_id else order.client_order_id)
            order.status=str(result.get("status","CANCELED"));order.updated_at=_now()
            if order.status in {"CANCELED","EXPIRED"}: cancelled.append(order.id)
            else: failed.append(order.id)
            db.commit()
        except Exception:
            db.rollback();failed.append(order.id)
    return cancelled,failed

@router.post("/kill-switch/global/activate")
async def activate_global_kill_switch(x_tradf_admin_token: str | None = Header(default=None),
                                      reason: str="Global emergency stop"):
    _require_admin_control(x_tradf_admin_token)
    lock_db=_db()
    db=_db()
    try:
        _acquire_execution_locks(lock_db)
        row=db.get(GlobalKillSwitch,1)
        if row is None:
            row=GlobalKillSwitch(id=1,enabled=True,reason=reason[:240],activated_at=_now(),updated_at=_now());db.add(row)
        else:
            row.enabled=True;row.reason=reason[:240];row.activated_at=_now();row.updated_at=_now()
        db.commit()
        cancelled,failed=await _cancel_all_open_testnet_orders(db)
        return {"global_kill_switch_enabled":True,"cancelled_order_ids":cancelled,
            "cancellation_failed_order_ids":failed,"all_open_orders_confirmed_cancelled":len(failed)==0,
            "filled_assets_liquidated":False}
    finally:
        db.close()
        lock_db.rollback()
        lock_db.close()

class GlobalResumeRequest(BaseModel):
    confirm_resume: bool
    reason: str = Field(default="Admin reviewed global resume",max_length=240)

@router.post("/kill-switch/global/resume")
def resume_global_kill_switch(payload: GlobalResumeRequest,
                              x_tradf_admin_token: str | None = Header(default=None)):
    _require_admin_control(x_tradf_admin_token)
    if not payload.confirm_resume: raise HTTPException(status_code=400,detail="confirm_resume=true is required")
    if os.getenv("TRADF_GLOBAL_KILL_SWITCH","true").strip().lower() in {"1","true","yes","on"}:
        raise HTTPException(status_code=423,detail="TRADF_GLOBAL_KILL_SWITCH environment override is still enabled")
    if not _testnet_orders_enabled(): raise HTTPException(status_code=423,detail="Testnet order placement remains disabled")
    if os.getenv("LIVE_TRADING_ENABLED","false").strip().lower() in {"1","true","yes","on"}:
        raise HTTPException(status_code=423,detail="Live trading must remain disabled")
    lock_db=_db()
    db=_db()
    try:
        _acquire_execution_locks(lock_db)
        open_count=db.scalar(select(func.count()).select_from(ExchangeOrder).where(
            ExchangeOrder.status.in_(["NEW","PARTIALLY_FILLED","PENDING_CANCEL","SUBMITTING","UNKNOWN"]))) or 0
        if open_count:
            raise HTTPException(status_code=423,detail="Cannot resume globally while open or ambiguous Testnet orders remain")
        row=db.get(GlobalKillSwitch,1)
        if row is None:
            row=GlobalKillSwitch(id=1,enabled=False,reason=payload.reason,updated_at=_now());db.add(row)
        else: row.enabled=False;row.reason=payload.reason;row.updated_at=_now()
        db.commit()
        return {"global_kill_switch_enabled":False,"live_trading_enabled":False,
            "note":"This permits only explicitly confirmed Testnet requests; no live trading is enabled."}
    finally:
        db.close()
        lock_db.rollback()
        lock_db.close()

class BurninStart(BaseModel):
    portfolio_id: str
    interval_seconds: int = Field(default=900,ge=300,le=3600)

@router.get("/status")
def production_status(user=Depends(current_user)):
    db=_db()
    try:
        global_kill=_global_kill_enabled(db)
    finally: db.close()
    return {"scope":"binance_spot_testnet_only","vault_ready":vault_ready(),
        "testnet_order_placement_enabled":_testnet_orders_enabled(),
        "global_kill_switch_enabled":global_kill,"live_trading_enabled":False,
        "scheduler_process":"separate_background_worker_required","execution_allowed":False}

@router.post("/exchange/testnet/credentials",status_code=201)
async def create_testnet_credential(payload: CredentialCreate,user=Depends(current_user)):
    if not payload.acknowledge_testnet_only:
        raise HTTPException(status_code=400,detail="Explicit testnet-only acknowledgement is required")
    if not vault_ready(): raise HTTPException(status_code=503,detail="Credential vault is not configured")
    db=_db()
    try:
        _owned_portfolio(db,user["id"],payload.portfolio_id)
        api_key_value=payload.api_key.get_secret_value()
        api_secret_value=payload.api_secret.get_secret_value()
        adapter=BinanceSpotTestnet(api_key_value,api_secret_value)
        try: verification=await adapter.verify_account()
        except ExchangeTestnetError as exc: raise HTTPException(status_code=exc.status_code,detail={"code":exc.code,"message":exc.message})
        row=ExchangeCredential(id=str(uuid.uuid4()),user_id=user["id"],portfolio_id=payload.portfolio_id,
            provider="binance_spot_testnet",label=payload.label.strip(),
            encrypted_api_key=encrypt_secret(api_key_value),encrypted_api_secret=encrypt_secret(api_secret_value),
            key_fingerprint=key_fingerprint(api_key_value),status="active",last_verified_at=_now())
        db.add(row)
        _audit_security_event(db,user["id"],"TESTNET_CREDENTIAL_CREATED",payload.portfolio_id,row.id,
            {"provider":row.provider,"key_fingerprint":row.key_fingerprint})
        db.commit()
        return {"id":row.id,"provider":row.provider,"label":row.label,"key_fingerprint":row.key_fingerprint,
            "status":row.status,"verified":True,"permissions":verification,"secret_returned":False}
    finally: db.close()

@router.get("/exchange/testnet/credentials")
def list_testnet_credentials(portfolio_id: str,user=Depends(current_user)):
    db=_db()
    try:
        _owned_portfolio(db,user["id"],portfolio_id)
        rows=db.scalars(select(ExchangeCredential).where(ExchangeCredential.user_id==user["id"],
            ExchangeCredential.portfolio_id==portfolio_id).order_by(ExchangeCredential.created_at.desc())).all()
        return {"items":[{"id":x.id,"provider":x.provider,"label":x.label,"key_fingerprint":x.key_fingerprint,
            "status":x.status,"last_verified_at":x.last_verified_at.isoformat() if x.last_verified_at else None,
            "created_at":x.created_at.isoformat() if x.created_at else None} for x in rows],
            "secret_returned":False}
    finally: db.close()

@router.delete("/exchange/testnet/credentials/{credential_id}")
def revoke_testnet_credential(credential_id: str,user=Depends(current_user)):
    lock_db=_db()
    db=_db()
    try:
        _acquire_execution_locks(lock_db,user["id"])
        row=db.scalar(select(ExchangeCredential).where(ExchangeCredential.id==credential_id,
            ExchangeCredential.user_id==user["id"]))
        if row is None: raise HTTPException(status_code=404,detail="Credential not found")
        open_count=db.scalar(select(func.count()).select_from(ExchangeOrder).where(
            ExchangeOrder.user_id==user["id"],ExchangeOrder.credential_id==credential_id,
            ExchangeOrder.status.in_(["NEW","PARTIALLY_FILLED","PENDING_CANCEL","SUBMITTING","UNKNOWN"]))) or 0
        if open_count:
            raise HTTPException(status_code=409,detail="Cancel or reconcile all open/unknown Testnet orders before revoking this credential")
        row.status="revoked";row.encrypted_api_key="";row.encrypted_api_secret="";row.updated_at=_now()
        _audit_security_event(db,user["id"],"TESTNET_CREDENTIAL_REVOKED",row.portfolio_id,row.id,{})
        db.commit()
        return {"revoked":True,"credential_id":credential_id}
    finally:
        db.close()
        lock_db.rollback()
        lock_db.close()

@router.post("/exchange/testnet/orders",status_code=201)
async def create_testnet_order(payload: LimitOrderCreate,user=Depends(current_user)):
    if not payload.confirm_testnet_only: raise HTTPException(status_code=400,detail="Testnet confirmation required")
    lock_db=_db()
    db=_db()
    try:
        _acquire_execution_locks(lock_db,user["id"])
        _execution_guard(db,user["id"])
        _owned_portfolio(db,user["id"],payload.portfolio_id)
        c=_credential(db,user["id"],payload.credential_id)
        if c.portfolio_id!=payload.portfolio_id: raise HTTPException(status_code=404,detail="Credential does not belong to portfolio")
        client_id="tdf"+hashlib.sha256((user["id"]+payload.portfolio_id+payload.client_request_id).encode()).hexdigest()[:32]
        existing=db.scalar(select(ExchangeOrder).where(ExchangeOrder.user_id==user["id"],ExchangeOrder.client_order_id==client_id))
        adapter=_adapter(c)
        if existing:
            if (existing.portfolio_id!=payload.portfolio_id or existing.symbol!=payload.symbol.upper()
                or existing.side!=payload.side or existing.quantity!=payload.quantity or existing.price!=payload.price):
                raise HTTPException(status_code=409,detail="Idempotency key was already used with different order parameters")
            # Never resubmit an ambiguous request. Query by deterministic client ID instead.
            if existing.status in {"SUBMITTING","UNKNOWN"}:
                try:
                    reconciled=await adapter.get_order(symbol=existing.symbol,client_order_id=existing.client_order_id)
                    existing.exchange_order_id=str(reconciled.get("orderId")) if reconciled.get("orderId") is not None else existing.exchange_order_id
                    existing.status=str(reconciled.get("status",existing.status))
                    existing.response_json={"status":existing.status,"reconciled":True}
                    existing.updated_at=_now();db.commit()
                except ExchangeTestnetError:
                    db.rollback()
            return {"id":existing.id,"status":existing.status,"client_order_id":existing.client_order_id,
                    "idempotent_replay":True,"resubmitted":False}
        # Persist intent before network I/O so a timeout cannot cause a duplicate order on retry.
        row=ExchangeOrder(id=str(uuid.uuid4()),user_id=user["id"],portfolio_id=payload.portfolio_id,
            credential_id=c.id,provider="binance_spot_testnet",symbol=payload.symbol.upper(),side=payload.side,
            quantity=payload.quantity,price=payload.price,client_order_id=client_id,status="SUBMITTING",
            response_json={"intent_persisted":True},updated_at=_now())
        db.add(row)
        _audit_security_event(db,user["id"],"TESTNET_ORDER_INTENT_RECORDED",payload.portfolio_id,row.id,
            {"symbol":row.symbol,"side":row.side,"order_type":"LIMIT","client_order_id":client_id})
        db.commit()
        try:
            await adapter.verify_account()
            response=await adapter.place_limit_order(symbol=payload.symbol.upper(),side=payload.side,
                quantity=payload.quantity,price=payload.price,client_order_id=client_id)
            row.exchange_order_id=str(response.get("orderId")) if response.get("orderId") is not None else None
            row.status=str(response.get("status","UNKNOWN"))
            row.response_json={"status":response.get("status"),"type":response.get("type"),
                "transactTime":response.get("transactTime")}
            row.updated_at=_now();db.commit()
        except ExchangeTestnetError as exc:
            row.status="REJECTED" if exc.status_code < 500 else "UNKNOWN"
            row.last_error_code=exc.code;row.response_json={"error_code":exc.code}
            row.updated_at=_now();db.commit()
            raise HTTPException(status_code=exc.status_code,detail={"code":exc.code,"message":exc.message})
        return {"id":row.id,"exchange_order_id":row.exchange_order_id,"client_order_id":client_id,
            "symbol":row.symbol,"side":row.side,"status":row.status,"provider":"binance_spot_testnet",
            "live_trading_enabled":False}
    finally:
        db.close()
        lock_db.rollback()
        lock_db.close()

@router.get("/exchange/testnet/orders")
def list_testnet_orders(portfolio_id: str,user=Depends(current_user)):
    db=_db()
    try:
        _owned_portfolio(db,user["id"],portfolio_id)
        rows=db.scalars(select(ExchangeOrder).where(ExchangeOrder.user_id==user["id"],
            ExchangeOrder.portfolio_id==portfolio_id).order_by(ExchangeOrder.created_at.desc()).limit(200)).all()
        return {"items":[{"id":x.id,"symbol":x.symbol,"side":x.side,"quantity":x.quantity,"price":x.price,
            "status":x.status,"exchange_order_id":x.exchange_order_id,"created_at":x.created_at.isoformat()} for x in rows]}
    finally: db.close()

@router.post("/exchange/testnet/orders/{order_id}/cancel")
async def cancel_testnet_order(order_id: str,user=Depends(current_user)):
    db=_db()
    try:
        row=db.scalar(select(ExchangeOrder).where(ExchangeOrder.id==order_id,ExchangeOrder.user_id==user["id"]))
        if row is None: raise HTTPException(status_code=404,detail="Order not found")
        if row.status not in {"NEW","PARTIALLY_FILLED","PENDING_CANCEL","SUBMITTING","UNKNOWN"}:
            return {"cancelled":False,"status":row.status,"reason":"Order is not open"}
        c=_credential(db,user["id"],row.credential_id)
        try:
            result=await _adapter(c).cancel_order(symbol=row.symbol,order_id=row.exchange_order_id,
                client_order_id=None if row.exchange_order_id else row.client_order_id)
        except ExchangeTestnetError as exc:
            raise HTTPException(status_code=exc.status_code,detail={"code":exc.code,"message":exc.message})
        row.status=str(result.get("status","CANCELED"));row.response_json={"status":row.status};row.updated_at=_now()
        _audit_security_event(db,user["id"],"TESTNET_ORDER_CANCEL_REQUESTED",row.portfolio_id,row.id,{"status":row.status})
        db.commit()
        return {"cancelled":row.status in {"CANCELED","EXPIRED"},"status":row.status}
    finally: db.close()

@router.get("/kill-switch")
def get_kill_switch(user=Depends(current_user)):
    db=_db()
    try:
        row=db.get(UserKillSwitch,user["id"])
        return {"user_kill_switch_enabled":True if row is None else row.enabled,
            "global_kill_switch_enabled":_global_kill_enabled(db),"effective_kill_switch_enabled":_global_kill_enabled(db) or row is None or row.enabled,
            "reason":row.reason if row else "Fail-closed default: explicit resume required",
            "filled_assets_liquidated":False,"live_trading_enabled":False}
    finally: db.close()

@router.post("/kill-switch/activate")
async def activate_kill_switch(reason: str="Emergency stop requested",user=Depends(current_user)):
    lock_db=_db()
    db=_db()
    try:
        _acquire_execution_locks(lock_db,user["id"])
        row=db.get(UserKillSwitch,user["id"])
        if row is None:
            row=UserKillSwitch(user_id=user["id"],enabled=True,reason=reason[:240],activated_at=_now(),updated_at=_now());db.add(row)
        else:
            row.enabled=True;row.reason=reason[:240];row.activated_at=_now();row.updated_at=_now()
        open_orders=db.scalars(select(ExchangeOrder).where(ExchangeOrder.user_id==user["id"],
            ExchangeOrder.status.in_(["NEW","PARTIALLY_FILLED","PENDING_CANCEL","SUBMITTING","UNKNOWN"]))).all()
        _audit_security_event(db,user["id"],"USER_KILL_SWITCH_ACTIVATED",None,None,{"reason":reason[:240]})
        db.commit()
        cancelled=[];failed=[]
        for order in open_orders:
            try:
                c=_credential(db,user["id"],order.credential_id)
                result=await _adapter(c).cancel_order(symbol=order.symbol,order_id=order.exchange_order_id,
                    client_order_id=None if order.exchange_order_id else order.client_order_id)
                order.status=str(result.get("status","CANCELED"));order.updated_at=_now()
                if order.status in {"CANCELED","EXPIRED"}: cancelled.append(order.id)
                else: failed.append(order.id)
                db.commit()
            except Exception:
                failed.append(order.id)
                db.rollback()
        return {"kill_switch_enabled":True,"cancelled_order_ids":cancelled,"cancellation_failed_order_ids":failed,
            "all_open_orders_confirmed_cancelled":len(failed)==0,"filled_assets_liquidated":False,
            "note":"Switch is active even if exchange cancellation failed; verify open orders directly in testnet."}
    finally:
        db.close()
        lock_db.rollback()
        lock_db.close()

class ResumeRequest(BaseModel):
    confirm_resume: bool
    reason: str = Field(default="Manual resume after review",max_length=240)

@router.post("/kill-switch/resume")
def resume_kill_switch(payload: ResumeRequest,user=Depends(current_user)):
    if not payload.confirm_resume: raise HTTPException(status_code=400,detail="confirm_resume=true is required")
    if not _testnet_orders_enabled():
        raise HTTPException(status_code=423,detail="Testnet order placement remains disabled in deployment configuration")
    lock_db=_db()
    db=_db()
    try:
        _acquire_execution_locks(lock_db,user["id"])
        if _global_kill_enabled(db): raise HTTPException(status_code=423,detail="Global emergency kill switch remains enabled")
        open_count=db.scalar(select(func.count()).select_from(ExchangeOrder).where(
            ExchangeOrder.user_id==user["id"],
            ExchangeOrder.status.in_(["NEW","PARTIALLY_FILLED","PENDING_CANCEL","SUBMITTING","UNKNOWN"]))) or 0
        if open_count:
            raise HTTPException(status_code=423,detail="Cannot resume while open or ambiguous Testnet orders remain")
        row=db.get(UserKillSwitch,user["id"])
        if row is None: row=UserKillSwitch(user_id=user["id"],enabled=False,reason=payload.reason,updated_at=_now());db.add(row)
        else: row.enabled=False;row.reason=payload.reason;row.updated_at=_now()
        _audit_security_event(db,user["id"],"USER_KILL_SWITCH_RESUMED",None,None,{"reason":payload.reason})
        db.commit()
        return {"user_kill_switch_enabled":False,"live_trading_enabled":False,
            "note":"This only permits separately confirmed testnet requests; no autonomous/live trading is enabled."}
    finally:
        db.close()
        lock_db.rollback()
        lock_db.close()

@router.post("/scheduler/paper-burnin/start",status_code=201)
def start_paper_burnin(payload: BurninStart,user=Depends(current_user)):
    db=_db()
    try:
        _owned_portfolio(db,user["id"],payload.portfolio_id)
        row=db.scalar(select(SchedulerJob).where(SchedulerJob.user_id==user["id"],
            SchedulerJob.portfolio_id==payload.portfolio_id, SchedulerJob.job_type=="paper_burnin_snapshot"))
        if row is None:
            row=SchedulerJob(id=str(uuid.uuid4()),user_id=user["id"],portfolio_id=payload.portfolio_id,
                job_type="paper_burnin_snapshot",interval_seconds=payload.interval_seconds,
                enabled=True,next_run_at=_now(),updated_at=_now());db.add(row)
        else:
            row.interval_seconds=payload.interval_seconds;row.enabled=True;row.next_run_at=_now()
            row.lease_owner=None;row.lease_until=None;row.updated_at=_now()
        _audit_security_event(db,user["id"],"PAPER_BURNIN_SCHEDULER_STARTED",payload.portfolio_id,row.id,
            {"interval_seconds":row.interval_seconds})
        db.commit()
        return {"job_id":row.id,"enabled":True,"interval_seconds":row.interval_seconds,
            "worker_required":True,"target_observation_days":21}
    finally: db.close()

@router.post("/scheduler/paper-burnin/stop")
def stop_paper_burnin(portfolio_id: str,user=Depends(current_user)):
    db=_db()
    try:
        _owned_portfolio(db,user["id"],portfolio_id)
        row=db.scalar(select(SchedulerJob).where(SchedulerJob.user_id==user["id"],
            SchedulerJob.portfolio_id==portfolio_id, SchedulerJob.job_type=="paper_burnin_snapshot"))
        if row: row.enabled=False;row.lease_owner=None;row.lease_until=None;row.updated_at=_now();db.commit()
        return {"stopped":True}
    finally: db.close()

@router.get("/scheduler/paper-burnin/status")
def paper_burnin_status(portfolio_id: str,user=Depends(current_user)):
    db=_db()
    try:
        _owned_portfolio(db,user["id"],portfolio_id)
        job=db.scalar(select(SchedulerJob).where(SchedulerJob.user_id==user["id"],
            SchedulerJob.portfolio_id==portfolio_id, SchedulerJob.job_type=="paper_burnin_snapshot"))
        if job is None: return {"status":"not_started","ready_for_review":False,"execution_allowed":False}
        rows=db.scalars(select(PaperBurninSample).where(PaperBurninSample.user_id==user["id"],
            PaperBurninSample.portfolio_id==portfolio_id).order_by(PaperBurninSample.sampled_at.asc())).all()
        first=rows[0].sampled_at if rows else None
        last=rows[-1].sampled_at if rows else None
        days=(last-first).total_seconds()/86400 if first and last else 0
        gaps=[(b.sampled_at-a.sampled_at).total_seconds() for a,b in zip(rows,rows[1:])]
        max_gap=max(gaps) if gaps else 0
        gap_limit=max(1800,int(job.interval_seconds)*2)
        latest_age=(_now()-last).total_seconds() if last else float("inf")
        latest_closed=int((rows[-1].metrics_json or {}).get("closed_trade_count",0)) if rows else 0
        passed=(days>=21 and len(rows)>=100 and job.enabled is True and
                max_gap<=gap_limit and 0<=latest_age<=gap_limit and latest_closed>=30)
        return {"status":"observation_complete_for_review" if passed else "collecting",
            "sample_count":len(rows),"observation_days":round(days,3),"target_days":21,
            "minimum_samples":100,"max_sample_gap_seconds":round(max_gap,1),
            "allowed_sample_gap_seconds":gap_limit,"latest_sample_age_seconds":round(latest_age,1) if rows else None,
            "latest_closed_paper_trades":latest_closed,"minimum_closed_paper_trades":30,
            "job_enabled":job.enabled,"last_run_at":job.last_run_at.isoformat() if job.last_run_at else None,
            "last_status":job.last_status,"last_error":job.last_error,
            "ready_for_review":passed,"execution_allowed":False,
            "note":"Requires 21 days, 100 snapshots, bounded sample gaps, a recent heartbeat and 30 closed paper trades. This is not proof of profitability or permission for live trading."}
    finally: db.close()

@router.get("/security/audit-snapshot")
def security_audit_snapshot(user=Depends(current_user)):
    db=_db()
    try:
        creds=db.scalar(select(func.count()).select_from(ExchangeCredential).where(ExchangeCredential.user_id==user["id"])) or 0
        jobs=db.scalar(select(func.count()).select_from(SchedulerJob).where(SchedulerJob.user_id==user["id"],SchedulerJob.enabled.is_(True))) or 0
        ks=db.get(UserKillSwitch,user["id"])
        checks=[
            {"control":"testnet_only_adapter","status":"passed"},
            {"control":"live_trading_disabled","status":"passed" if os.getenv("LIVE_TRADING_ENABLED","false").lower()!="true" else "failed"},
            {"control":"credential_encryption_key_configured","status":"passed" if vault_ready() else "failed"},
            {"control":"global_kill_switch","status":"enabled" if _global_kill_enabled(db) else "disabled"},
            {"control":"user_kill_switch","status":"enabled" if ks is None or ks.enabled else "disabled"},
            {"control":"durable_scheduler_jobs","status":"configured" if jobs else "not_configured"},
            {"control":"third_party_penetration_test","status":"not_performed"},
        ]
        return {"status":"review_required","checks":checks,"active_credentials":creds,
            "active_scheduler_jobs":jobs,"secrets_returned":False,"live_trading_enabled":False,
            "independent_audit_required":True,
            "note":"This is a self-assessment snapshot. It is not an independent penetration test or certification."}
    finally: db.close()

def run_due_jobs_once(worker_id: str | None = None) -> bool:
    """Claim one due job with PostgreSQL SKIP LOCKED; lease expiry permits restart recovery."""
    from .database import get_session_factory
    from .db_models import ExecutionTrade
    worker_id=worker_id or f"{socket.gethostname()}-{uuid.uuid4().hex[:10]}"
    db=_db()
    job=None
    try:
        job=db.scalar(select(SchedulerJob).where(SchedulerJob.enabled.is_(True),
            SchedulerJob.next_run_at<=_now(),
            ((SchedulerJob.lease_until.is_(None)) | (SchedulerJob.lease_until<_now())))
            .order_by(SchedulerJob.next_run_at.asc()).with_for_update(skip_locked=True).limit(1))
        if job is None:
            db.rollback();return False
        job.lease_owner=worker_id;job.lease_until=_now()+timedelta(seconds=120);job.updated_at=_now()
        db.commit()
        job_id,user_id,portfolio_id,interval,scheduled_for=job.id,job.user_id,job.portfolio_id,job.interval_seconds,job.next_run_at
    finally: db.close()
    status="ok"; error=None
    try:
        db=_db()
        try:
            trades=db.scalars(select(ExecutionTrade).where(ExecutionTrade.user_id==user_id,
                ExecutionTrade.portfolio_id==portfolio_id)).all()
            active=sum(1 for t in trades if t.status in {"pending_entry","open","partially_closed"} and t.remaining_quantity>0)
            realized=sum(float(t.realized_pnl or 0)-float(t.fees_paid or 0) for t in trades)
            metrics={"trade_count":len(trades),"active_trade_count":active,
                "closed_trade_count":sum(1 for t in trades if t.status=="closed"),
                "net_realized_pnl":round(realized,8),"paper_only":True}
            prior=db.scalar(select(PaperBurninSample).where(
                PaperBurninSample.job_id==job_id,PaperBurninSample.scheduled_for==scheduled_for))
            if prior is None:
                db.add(PaperBurninSample(job_id=job_id,user_id=user_id,portfolio_id=portfolio_id,
                    scheduled_for=scheduled_for,sampled_at=_now(),metrics_json=metrics))
                db.commit()
        finally: db.close()
    except Exception as exc:
        status="error";error=type(exc).__name__
    db=_db()
    try:
        row=db.get(SchedulerJob,job_id)
        if row and row.lease_owner==worker_id:
            row.last_run_at=_now();row.last_status=status;row.last_error=error
            row.next_run_at=_now()+timedelta(seconds=interval);row.lease_owner=None;row.lease_until=None;row.updated_at=_now()
            db.commit()
    finally: db.close()
    return True
