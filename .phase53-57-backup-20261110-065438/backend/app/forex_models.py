"""Database models for broker-independent FX paper research."""
from __future__ import annotations
from datetime import datetime
from sqlalchemy import (
    BigInteger, CheckConstraint, DateTime, Float, ForeignKey, Index,
    Integer, JSON, String, Text, UniqueConstraint, func,
)
from sqlalchemy.orm import Mapped, mapped_column
from .database import Base


class ForexCandle(Base):
    __tablename__ = "tradf_forex_candles"
    __table_args__ = (
        CheckConstraint("open > 0 AND high > 0 AND low > 0 AND close > 0", name="ck_tradf_fx_candle_positive"),
        CheckConstraint("high >= low AND high >= open AND high >= close", name="ck_tradf_fx_candle_high"),
        CheckConstraint("low <= open AND low <= close", name="ck_tradf_fx_candle_low"),
        Index("ix_tradf_fx_candle_symbol_tf_time", "symbol", "timeframe", "candle_time"),
    )
    symbol: Mapped[str] = mapped_column(String(16), primary_key=True)
    timeframe: Mapped[str] = mapped_column(String(8), primary_key=True)
    candle_time: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    open: Mapped[float] = mapped_column(Float, nullable=False)
    high: Mapped[float] = mapped_column(Float, nullable=False)
    low: Mapped[float] = mapped_column(Float, nullable=False)
    close: Mapped[float] = mapped_column(Float, nullable=False)
    volume: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class ForexPaperRun(Base):
    __tablename__ = "tradf_forex_paper_runs"
    __table_args__ = (
        CheckConstraint("risk_per_trade_pct > 0 AND risk_per_trade_pct <= 2", name="ck_tradf_fx_run_risk"),
        CheckConstraint("initial_equity > 0", name="ck_tradf_fx_run_equity"),
        Index("ix_tradf_fx_runs_owner_status", "user_id", "portfolio_id", "status"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("v11_users.id", ondelete="CASCADE"), nullable=False, index=True)
    portfolio_id: Mapped[str] = mapped_column(ForeignKey("v11_portfolios.id", ondelete="CASCADE"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    symbols: Mapped[list] = mapped_column(JSON, nullable=False)
    initial_equity: Mapped[float] = mapped_column(Float, nullable=False)
    risk_per_trade_pct: Mapped[float] = mapped_column(Float, nullable=False, default=0.25)
    min_quality_score: Mapped[int] = mapped_column(Integer, nullable=False, default=65)
    min_rr: Mapped[float] = mapped_column(Float, nullable=False, default=2.0)
    commission_pct: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    spread_bps: Mapped[float] = mapped_column(Float, nullable=False, default=1.5)
    slippage_bps: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    realized_pnl_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    fees_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    stopped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_tick_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class ForexPaperTrade(Base):
    __tablename__ = "tradf_forex_paper_trades"
    __table_args__ = (
        UniqueConstraint("run_id", "symbol", "signal_time", "direction", name="uq_tradf_fx_trade_signal"),
        UniqueConstraint("run_id", "symbol", "zone_key", name="uq_tradf_fx_trade_zone"),
        CheckConstraint("quantity > 0 AND remaining_quantity >= 0", name="ck_tradf_fx_trade_quantity"),
        Index("ix_tradf_fx_trades_run_status", "run_id", "status"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("tradf_forex_paper_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("v11_users.id", ondelete="CASCADE"), nullable=False, index=True)
    portfolio_id: Mapped[str] = mapped_column(ForeignKey("v11_portfolios.id", ondelete="CASCADE"), nullable=False, index=True)
    symbol: Mapped[str] = mapped_column(String(16), nullable=False)
    direction: Mapped[str] = mapped_column(String(8), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending_entry")
    signal_time: Mapped[int] = mapped_column(BigInteger, nullable=False)
    zone_key: Mapped[str] = mapped_column(String(240), nullable=False)
    quality_score: Mapped[int] = mapped_column(Integer, nullable=False)
    planned_entry: Mapped[float] = mapped_column(Float, nullable=False)
    actual_entry: Mapped[float | None] = mapped_column(Float)
    stop_loss: Mapped[float] = mapped_column(Float, nullable=False)
    initial_stop_loss: Mapped[float] = mapped_column(Float, nullable=False)
    take_profits: Mapped[list] = mapped_column(JSON, nullable=False)
    next_target_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    quantity: Mapped[float] = mapped_column(Float, nullable=False)
    remaining_quantity: Mapped[float] = mapped_column(Float, nullable=False)
    risk_cash_usd: Mapped[float] = mapped_column(Float, nullable=False)
    realized_pnl_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    fees_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    last_event_time_ms: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    entry_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class ForexPaperEvent(Base):
    __tablename__ = "tradf_forex_paper_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    trade_id: Mapped[str] = mapped_column(ForeignKey("tradf_forex_paper_trades.id", ondelete="CASCADE"), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    market_price: Mapped[float] = mapped_column(Float, nullable=False)
    fill_price: Mapped[float | None] = mapped_column(Float)
    quantity: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    pnl_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    fee_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    event_time_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    details_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class ForexWorkerState(Base):
    __tablename__ = "tradf_forex_worker_state"
    __table_args__ = (CheckConstraint("id = 1", name="ck_tradf_forex_worker_singleton"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    worker_id: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="starting")
    subscribed_symbols: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    last_tick_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    heartbeat_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    last_error: Mapped[str | None] = mapped_column(String(240))
