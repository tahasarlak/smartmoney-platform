from __future__ import annotations
from datetime import datetime
from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column
from .database import Base

class ExchangeCredential(Base):
    __tablename__ = "tradf_exchange_credentials"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("v11_users.id", ondelete="CASCADE"), nullable=False, index=True)
    portfolio_id: Mapped[str] = mapped_column(ForeignKey("v11_portfolios.id", ondelete="CASCADE"), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(24), nullable=False, default="binance_spot_testnet")
    label: Mapped[str] = mapped_column(String(80), nullable=False)
    encrypted_api_key: Mapped[str] = mapped_column(Text, nullable=False)
    encrypted_api_secret: Mapped[str] = mapped_column(Text, nullable=False)
    key_fingerprint: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

class ExchangeOrder(Base):
    __tablename__ = "tradf_exchange_orders"
    __table_args__ = (
        UniqueConstraint("user_id", "client_order_id", name="uq_tradf_exchange_user_client_order"),
        Index("ix_tradf_exchange_orders_owner_status", "user_id", "status"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("v11_users.id", ondelete="CASCADE"), nullable=False, index=True)
    portfolio_id: Mapped[str] = mapped_column(ForeignKey("v11_portfolios.id", ondelete="CASCADE"), nullable=False, index=True)
    credential_id: Mapped[str] = mapped_column(ForeignKey("tradf_exchange_credentials.id", ondelete="RESTRICT"), nullable=False)
    provider: Mapped[str] = mapped_column(String(24), nullable=False, default="binance_spot_testnet")
    symbol: Mapped[str] = mapped_column(String(30), nullable=False)
    side: Mapped[str] = mapped_column(String(4), nullable=False)
    order_type: Mapped[str] = mapped_column(String(12), nullable=False, default="LIMIT")
    quantity: Mapped[str] = mapped_column(String(40), nullable=False)
    price: Mapped[str] = mapped_column(String(40), nullable=False)
    client_order_id: Mapped[str] = mapped_column(String(36), nullable=False)
    exchange_order_id: Mapped[str | None] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="SUBMITTING")
    response_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    last_error_code: Mapped[str | None] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

class GlobalKillSwitch(Base):
    __tablename__ = "tradf_global_kill_switch"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    reason: Mapped[str] = mapped_column(String(240), nullable=False, default="Safe default")
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

class UserKillSwitch(Base):
    __tablename__ = "tradf_user_kill_switches"
    user_id: Mapped[str] = mapped_column(ForeignKey("v11_users.id", ondelete="CASCADE"), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    reason: Mapped[str] = mapped_column(String(240), nullable=False, default="Default safe state")
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

class SchedulerJob(Base):
    __tablename__ = "tradf_scheduler_jobs"
    __table_args__ = (
        UniqueConstraint("user_id", "portfolio_id", "job_type", name="uq_tradf_scheduler_owner_portfolio_type"),
        Index("ix_tradf_scheduler_due", "enabled", "next_run_at", "lease_until"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("v11_users.id", ondelete="CASCADE"), nullable=False, index=True)
    portfolio_id: Mapped[str] = mapped_column(ForeignKey("v11_portfolios.id", ondelete="CASCADE"), nullable=False, index=True)
    job_type: Mapped[str] = mapped_column(String(40), nullable=False)
    interval_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=900)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    next_run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    lease_owner: Mapped[str | None] = mapped_column(String(80))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_status: Mapped[str | None] = mapped_column(String(24))
    last_error: Mapped[str | None] = mapped_column(String(240))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

class PaperBurninSample(Base):
    __tablename__ = "tradf_paper_burnin_samples"
    __table_args__ = (UniqueConstraint("job_id", "scheduled_for", name="uq_tradf_burnin_job_slot"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("tradf_scheduler_jobs.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("v11_users.id", ondelete="CASCADE"), nullable=False, index=True)
    portfolio_id: Mapped[str] = mapped_column(ForeignKey("v11_portfolios.id", ondelete="CASCADE"), nullable=False, index=True)
    scheduled_for: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    sampled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    metrics_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
