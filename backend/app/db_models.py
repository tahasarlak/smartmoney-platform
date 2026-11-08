from __future__ import annotations

from datetime import datetime
from sqlalchemy import (
    BigInteger, Boolean, CheckConstraint, DateTime, Float, ForeignKey,
    Index, Integer, JSON, String, Text, UniqueConstraint, func
)
from sqlalchemy.orm import Mapped, mapped_column
from .database import Base

class User(Base):
    __tablename__ = "v11_users"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

class Session(Base):
    __tablename__ = "v11_sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("v11_users.id", ondelete="CASCADE"), nullable=False, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

class Portfolio(Base):
    __tablename__ = "v11_portfolios"
    __table_args__ = (
        CheckConstraint("max_open_trades BETWEEN 1 AND 100"),
        CheckConstraint("max_portfolio_risk_pct BETWEEN 0 AND 100"),
        CheckConstraint("max_trade_risk_pct BETWEEN 0 AND 100"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("v11_users.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    base_currency: Mapped[str] = mapped_column(String(12), nullable=False, default="USDT")
    initial_equity: Mapped[float] = mapped_column(Float, nullable=False)
    max_open_trades: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    max_portfolio_risk_pct: Mapped[float] = mapped_column(Float, nullable=False, default=3)
    max_trade_risk_pct: Mapped[float] = mapped_column(Float, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

class BrokerAccount(Base):
    __tablename__ = "v11_broker_accounts"
    __table_args__ = (
        CheckConstraint("broker IN ('binance','mt5')"),
        CheckConstraint("mode = 'paper'"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("v11_users.id", ondelete="CASCADE"), nullable=False, index=True)
    portfolio_id: Mapped[str] = mapped_column(ForeignKey("v11_portfolios.id", ondelete="CASCADE"), nullable=False, index=True)
    broker: Mapped[str] = mapped_column(String(20), nullable=False)
    mode: Mapped[str] = mapped_column(String(12), nullable=False, default="paper")
    label: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

class PaperOrder(Base):
    __tablename__ = "v11_paper_orders"
    __table_args__ = (
        CheckConstraint("broker IN ('binance','mt5')"),
        CheckConstraint("side IN ('long','short')"),
        CheckConstraint("quantity > 0 AND entry_price > 0 AND stop_loss > 0 AND take_profit > 0"),
        CheckConstraint("risk_cash >= 0"),
        CheckConstraint("status IN ('open','closed')"),
        Index("idx_v11_orders_portfolio_status", "portfolio_id", "status"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("v11_users.id", ondelete="CASCADE"), nullable=False, index=True)
    portfolio_id: Mapped[str] = mapped_column(ForeignKey("v11_portfolios.id", ondelete="CASCADE"), nullable=False, index=True)
    account_id: Mapped[str] = mapped_column(ForeignKey("v11_broker_accounts.id", ondelete="CASCADE"), nullable=False)
    broker: Mapped[str] = mapped_column(String(20), nullable=False)
    symbol: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    side: Mapped[str] = mapped_column(String(8), nullable=False)
    quantity: Mapped[float] = mapped_column(Float, nullable=False)
    entry_price: Mapped[float] = mapped_column(Float, nullable=False)
    stop_loss: Mapped[float] = mapped_column(Float, nullable=False)
    take_profit: Mapped[float] = mapped_column(Float, nullable=False)
    risk_cash: Mapped[float] = mapped_column(Float, nullable=False)
    status: Mapped[str] = mapped_column(String(12), nullable=False)
    exit_price: Mapped[float | None] = mapped_column(Float)
    realized_pnl: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

class AuditEvent(Base):
    __tablename__ = "v11_audit_events"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("v11_users.id", ondelete="CASCADE"), nullable=False, index=True)
    portfolio_id: Mapped[str | None] = mapped_column(String(36))
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    entity_id: Mapped[str | None] = mapped_column(String(36))
    details_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

class BacktestRun(Base):
    __tablename__ = "v11_backtest_runs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("v11_users.id", ondelete="CASCADE"), nullable=False, index=True)
    portfolio_id: Mapped[str] = mapped_column(ForeignKey("v11_portfolios.id", ondelete="CASCADE"), nullable=False, index=True)
    result_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

class MarketPrice(Base):
    __tablename__ = "market_prices"
    symbol: Mapped[str] = mapped_column(String(40), primary_key=True)
    price: Mapped[float] = mapped_column(Float, nullable=False)
    event_time: Mapped[str] = mapped_column(Text, nullable=False)
    event_time_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    __table_args__ = (CheckConstraint("price > 0"), Index("idx_market_prices_updated", "updated_at"))

class MarketWatchlist(Base):
    __tablename__ = "market_watchlist"
    symbol: Mapped[str] = mapped_column(String(40), primary_key=True)
    provider: Mapped[str] = mapped_column(String(40), nullable=False, default="binance_spot")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

class Signal(Base):
    __tablename__ = "signals"
    __table_args__ = (
        CheckConstraint("direction IN ('bullish','bearish')"),
        CheckConstraint("visibility IN ('public','private')"),
        CheckConstraint("(visibility = 'public' AND user_id IS NULL) OR (visibility = 'private' AND user_id IS NOT NULL)"),
        Index("idx_signals_status_created", "status", "created_at"),
        Index("idx_signals_symbol_created", "symbol", "created_at"),
        Index("idx_signals_owner_created", "user_id", "created_at"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("v11_users.id", ondelete="CASCADE"), nullable=True)
    visibility: Mapped[str] = mapped_column(String(10), nullable=False, default="public")
    symbol: Mapped[str] = mapped_column(String(40), nullable=False)
    direction: Mapped[str] = mapped_column(String(8), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    setup_class: Mapped[str | None] = mapped_column(String(80))
    quality_score: Mapped[int | None] = mapped_column(Integer)
    entry: Mapped[float] = mapped_column(Float, nullable=False)
    stop_loss: Mapped[float] = mapped_column(Float, nullable=False)
    tp1: Mapped[float] = mapped_column(Float, nullable=False)
    tp2: Mapped[float] = mapped_column(Float, nullable=False)
    tp3: Mapped[float] = mapped_column(Float, nullable=False)
    zone_low: Mapped[float | None] = mapped_column(Float)
    zone_high: Mapped[float | None] = mapped_column(Float)
    min_rr: Mapped[float | None] = mapped_column(Float)
    risk_percent: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    last_price: Mapped[float | None] = mapped_column(Float)
    last_price_at: Mapped[str | None] = mapped_column(Text)
    closed_at: Mapped[str | None] = mapped_column(Text)
    close_reason: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(40), nullable=False, default="research")

class SignalEvent(Base):
    __tablename__ = "signal_events"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    signal_id: Mapped[str] = mapped_column(ForeignKey("signals.id", ondelete="CASCADE"), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(60), nullable=False)
    old_status: Mapped[str | None] = mapped_column(String(40))
    new_status: Mapped[str | None] = mapped_column(String(40))
    price: Mapped[float | None] = mapped_column(Float)
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class ForwardTestRun(Base):
    """Tenant-scoped, market-tick-driven paper forward-test session."""
    __tablename__ = "v11_forward_test_runs"
    __table_args__ = (
        CheckConstraint("status IN ('active','stopping','stopped')"),
        CheckConstraint("initial_equity > 0"),
        CheckConstraint("risk_per_trade_pct > 0 AND risk_per_trade_pct <= 100"),
        CheckConstraint("commission_pct >= 0 AND commission_pct <= 5"),
        CheckConstraint("slippage_bps >= 0 AND slippage_bps <= 1000"),
        Index("idx_forward_runs_owner_status", "user_id", "status"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("v11_users.id", ondelete="CASCADE"), nullable=False, index=True)
    portfolio_id: Mapped[str] = mapped_column(ForeignKey("v11_portfolios.id", ondelete="CASCADE"), nullable=False, index=True)
    account_id: Mapped[str] = mapped_column(ForeignKey("v11_broker_accounts.id", ondelete="CASCADE"), nullable=False)
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="active")
    symbols: Mapped[list] = mapped_column(JSON, nullable=False)
    initial_equity: Mapped[float] = mapped_column(Float, nullable=False)
    risk_per_trade_pct: Mapped[float] = mapped_column(Float, nullable=False)
    min_quality_score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    commission_pct: Mapped[float] = mapped_column(Float, nullable=False, default=0.04)
    slippage_bps: Mapped[float] = mapped_column(Float, nullable=False, default=2.0)
    include_existing_signals: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    stopped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    realized_pnl: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    fees_paid: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class ForwardTestTrade(Base):
    """One signal tracked by one forward-test run; targets are partial exits."""
    __tablename__ = "v11_forward_test_trades"
    __table_args__ = (
        UniqueConstraint("run_id", "signal_id", name="uq_forward_trade_run_signal"),
        CheckConstraint("direction IN ('long','short')"),
        CheckConstraint("status IN ('pending_entry','open','tp1_hit','tp2_hit','tp3_hit','stopped')"),
        CheckConstraint("quantity > 0 AND remaining_quantity >= 0"),
        CheckConstraint("planned_entry > 0 AND stop_loss > 0 AND tp1 > 0 AND tp2 > 0 AND tp3 > 0"),
        Index("idx_forward_trades_run_status", "run_id", "status"),
        Index("idx_forward_trades_user_created", "user_id", "created_at"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("v11_forward_test_runs.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[str] = mapped_column(ForeignKey("v11_users.id", ondelete="CASCADE"), nullable=False, index=True)
    portfolio_id: Mapped[str] = mapped_column(ForeignKey("v11_portfolios.id", ondelete="CASCADE"), nullable=False, index=True)
    signal_id: Mapped[str] = mapped_column(ForeignKey("signals.id", ondelete="CASCADE"), nullable=False)
    symbol: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    direction: Mapped[str] = mapped_column(String(8), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending_entry")
    quality_score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    planned_entry: Mapped[float] = mapped_column(Float, nullable=False)
    actual_entry: Mapped[float | None] = mapped_column(Float)
    stop_loss: Mapped[float] = mapped_column(Float, nullable=False)
    tp1: Mapped[float] = mapped_column(Float, nullable=False)
    tp2: Mapped[float] = mapped_column(Float, nullable=False)
    tp3: Mapped[float] = mapped_column(Float, nullable=False)
    quantity: Mapped[float] = mapped_column(Float, nullable=False)
    remaining_quantity: Mapped[float] = mapped_column(Float, nullable=False)
    risk_cash: Mapped[float] = mapped_column(Float, nullable=False)
    realized_pnl: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    fees_paid: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    last_price: Mapped[float | None] = mapped_column(Float)
    last_event_time_ms: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    last_event_id: Mapped[str | None] = mapped_column(String(80))
    entry_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class ForwardTestEvent(Base):
    __tablename__ = "v11_forward_test_events"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    trade_id: Mapped[str] = mapped_column(ForeignKey("v11_forward_test_trades.id", ondelete="CASCADE"), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(40), nullable=False)
    market_price: Mapped[float] = mapped_column(Float, nullable=False)
    fill_price: Mapped[float | None] = mapped_column(Float)
    quantity: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    pnl: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    fee: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    event_time_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    event_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    details_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
