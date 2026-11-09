"""Persist read-only MT5 demo market data and bridge heartbeat.

Revision ID: 0006_mt5_market_data
Revises: 0005_tradf_worker_heartbeat
"""
from alembic import op
import sqlalchemy as sa

revision = "0006_mt5_market_data"
down_revision = "0005_tradf_worker_heartbeat"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "tradf_mt5_market_candles",
        sa.Column("symbol", sa.String(16), primary_key=True),
        sa.Column("timeframe", sa.String(8), primary_key=True),
        sa.Column("candle_time", sa.Integer(), primary_key=True),
        sa.Column("open", sa.Float(), nullable=False),
        sa.Column("high", sa.Float(), nullable=False),
        sa.Column("low", sa.Float(), nullable=False),
        sa.Column("close", sa.Float(), nullable=False),
        sa.Column("volume", sa.Float(), nullable=False, server_default="0"),
        sa.Column("spread_points", sa.Integer()),
        sa.Column("broker_symbol", sa.String(40), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("open > 0 AND high > 0 AND low > 0 AND close > 0", name="ck_tradf_mt5_positive_prices"),
        sa.CheckConstraint("high >= low AND high >= open AND high >= close", name="ck_tradf_mt5_high_valid"),
        sa.CheckConstraint("low <= open AND low <= close", name="ck_tradf_mt5_low_valid"),
        sa.CheckConstraint("volume >= 0", name="ck_tradf_mt5_volume_nonnegative"),
    )
    op.create_index(
        "ix_tradf_mt5_candles_symbol_tf_time",
        "tradf_mt5_market_candles",
        ["symbol", "timeframe", "candle_time"],
    )

    op.create_table(
        "tradf_mt5_bridge_heartbeats",
        sa.Column("bridge_id", sa.String(80), primary_key=True),
        sa.Column("broker_server", sa.String(120), nullable=False),
        sa.Column("terminal_version", sa.String(80), nullable=False),
        sa.Column("account_mode", sa.String(12), nullable=False, server_default="demo"),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="connected"),
        sa.Column("last_error", sa.String(240)),
    )
    op.create_index(
        "ix_tradf_mt5_bridge_heartbeats_last_seen_at",
        "tradf_mt5_bridge_heartbeats",
        ["last_seen_at"],
    )


def downgrade():
    op.drop_index("ix_tradf_mt5_bridge_heartbeats_last_seen_at", table_name="tradf_mt5_bridge_heartbeats")
    op.drop_table("tradf_mt5_bridge_heartbeats")
    op.drop_index("ix_tradf_mt5_candles_symbol_tf_time", table_name="tradf_mt5_market_candles")
    op.drop_table("tradf_mt5_market_candles")
