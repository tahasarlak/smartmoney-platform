"""Add independent Forex candles and 21-day paper trading journal.

Revision ID: 0007_forex_intraday_paper
Revises: 0006_mt5_market_data
"""
from alembic import op
import sqlalchemy as sa

revision = "0007_forex_intraday_paper"
down_revision = "0006_mt5_market_data"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "tradf_forex_candles",
        sa.Column("symbol", sa.String(16), primary_key=True),
        sa.Column("timeframe", sa.String(8), primary_key=True),
        sa.Column("candle_time", sa.BigInteger(), primary_key=True),
        sa.Column("open", sa.Float(), nullable=False),
        sa.Column("high", sa.Float(), nullable=False),
        sa.Column("low", sa.Float(), nullable=False),
        sa.Column("close", sa.Float(), nullable=False),
        sa.Column("volume", sa.Float(), nullable=False, server_default="0"),
        sa.Column("provider", sa.String(40), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("open > 0 AND high > 0 AND low > 0 AND close > 0", name="ck_tradf_fx_candle_positive"),
        sa.CheckConstraint("high >= low AND high >= open AND high >= close", name="ck_tradf_fx_candle_high"),
        sa.CheckConstraint("low <= open AND low <= close", name="ck_tradf_fx_candle_low"),
    )
    op.create_index("ix_tradf_fx_candle_symbol_tf_time", "tradf_forex_candles", ["symbol", "timeframe", "candle_time"])

    op.create_table(
        "tradf_forex_paper_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("v11_users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("portfolio_id", sa.String(36), sa.ForeignKey("v11_portfolios.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        sa.Column("symbols", sa.JSON(), nullable=False),
        sa.Column("initial_equity", sa.Float(), nullable=False),
        sa.Column("risk_per_trade_pct", sa.Float(), nullable=False, server_default="0.25"),
        sa.Column("min_quality_score", sa.Integer(), nullable=False, server_default="65"),
        sa.Column("min_rr", sa.Float(), nullable=False, server_default="0.5"),
        sa.Column("commission_pct", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("spread_bps", sa.Float(), nullable=False, server_default="1.5"),
        sa.Column("slippage_bps", sa.Float(), nullable=False, server_default="0.5"),
        sa.Column("realized_pnl_usd", sa.Float(), nullable=False, server_default="0"),
        sa.Column("fees_usd", sa.Float(), nullable=False, server_default="0"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("stopped_at", sa.DateTime(timezone=True)),
        sa.Column("last_tick_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("risk_per_trade_pct > 0 AND risk_per_trade_pct <= 2", name="ck_tradf_fx_run_risk"),
        sa.CheckConstraint("initial_equity > 0", name="ck_tradf_fx_run_equity"),
    )
    op.create_index("ix_tradf_forex_paper_runs_user_id", "tradf_forex_paper_runs", ["user_id"])
    op.create_index("ix_tradf_forex_paper_runs_portfolio_id", "tradf_forex_paper_runs", ["portfolio_id"])
    op.create_index("ix_tradf_fx_runs_owner_status", "tradf_forex_paper_runs", ["user_id", "portfolio_id", "status"])

    op.create_table(
        "tradf_forex_paper_trades",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("run_id", sa.String(36), sa.ForeignKey("tradf_forex_paper_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("v11_users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("portfolio_id", sa.String(36), sa.ForeignKey("v11_portfolios.id", ondelete="CASCADE"), nullable=False),
        sa.Column("symbol", sa.String(16), nullable=False),
        sa.Column("direction", sa.String(8), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending_entry"),
        sa.Column("signal_time", sa.BigInteger(), nullable=False),
        sa.Column("zone_key", sa.String(240), nullable=False),
        sa.Column("quality_score", sa.Integer(), nullable=False),
        sa.Column("planned_entry", sa.Float(), nullable=False),
        sa.Column("actual_entry", sa.Float()),
        sa.Column("stop_loss", sa.Float(), nullable=False),
        sa.Column("initial_stop_loss", sa.Float(), nullable=False),
        sa.Column("take_profits", sa.JSON(), nullable=False),
        sa.Column("next_target_index", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("quantity", sa.Float(), nullable=False),
        sa.Column("remaining_quantity", sa.Float(), nullable=False),
        sa.Column("risk_cash_usd", sa.Float(), nullable=False),
        sa.Column("realized_pnl_usd", sa.Float(), nullable=False, server_default="0"),
        sa.Column("fees_usd", sa.Float(), nullable=False, server_default="0"),
        sa.Column("last_event_time_ms", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("entry_time", sa.DateTime(timezone=True)),
        sa.Column("closed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("quantity > 0 AND remaining_quantity >= 0", name="ck_tradf_fx_trade_quantity"),
        sa.UniqueConstraint("run_id", "symbol", "signal_time", "direction", name="uq_tradf_fx_trade_signal"),
        sa.UniqueConstraint("run_id", "symbol", "zone_key", name="uq_tradf_fx_trade_zone"),
    )
    op.create_index("ix_tradf_forex_paper_trades_run_id", "tradf_forex_paper_trades", ["run_id"])
    op.create_index("ix_tradf_forex_paper_trades_user_id", "tradf_forex_paper_trades", ["user_id"])
    op.create_index("ix_tradf_forex_paper_trades_portfolio_id", "tradf_forex_paper_trades", ["portfolio_id"])
    op.create_index("ix_tradf_fx_trades_run_status", "tradf_forex_paper_trades", ["run_id", "status"])

    op.create_table(
        "tradf_forex_paper_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("trade_id", sa.String(36), sa.ForeignKey("tradf_forex_paper_trades.id", ondelete="CASCADE"), nullable=False),
        sa.Column("event_type", sa.String(32), nullable=False),
        sa.Column("market_price", sa.Float(), nullable=False),
        sa.Column("fill_price", sa.Float()),
        sa.Column("quantity", sa.Float(), nullable=False, server_default="0"),
        sa.Column("pnl_usd", sa.Float(), nullable=False, server_default="0"),
        sa.Column("fee_usd", sa.Float(), nullable=False, server_default="0"),
        sa.Column("event_time_ms", sa.BigInteger(), nullable=False),
        sa.Column("details_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_tradf_forex_paper_events_trade_id", "tradf_forex_paper_events", ["trade_id"])

    op.create_table(
        "tradf_forex_worker_state",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("worker_id", sa.String(120), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="starting"),
        sa.Column("subscribed_symbols", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("last_tick_at", sa.DateTime(timezone=True)),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("last_error", sa.String(240)),
        sa.CheckConstraint("id = 1", name="ck_tradf_forex_worker_singleton"),
    )


def downgrade():
    op.drop_table("tradf_forex_worker_state")
    op.drop_index("ix_tradf_forex_paper_events_trade_id", table_name="tradf_forex_paper_events")
    op.drop_table("tradf_forex_paper_events")
    op.drop_index("ix_tradf_fx_trades_run_status", table_name="tradf_forex_paper_trades")
    op.drop_index("ix_tradf_forex_paper_trades_portfolio_id", table_name="tradf_forex_paper_trades")
    op.drop_index("ix_tradf_forex_paper_trades_user_id", table_name="tradf_forex_paper_trades")
    op.drop_index("ix_tradf_forex_paper_trades_run_id", table_name="tradf_forex_paper_trades")
    op.drop_table("tradf_forex_paper_trades")
    op.drop_index("ix_tradf_fx_runs_owner_status", table_name="tradf_forex_paper_runs")
    op.drop_index("ix_tradf_forex_paper_runs_portfolio_id", table_name="tradf_forex_paper_runs")
    op.drop_index("ix_tradf_forex_paper_runs_user_id", table_name="tradf_forex_paper_runs")
    op.drop_table("tradf_forex_paper_runs")
    op.drop_index("ix_tradf_fx_candle_symbol_tf_time", table_name="tradf_forex_candles")
    op.drop_table("tradf_forex_candles")
