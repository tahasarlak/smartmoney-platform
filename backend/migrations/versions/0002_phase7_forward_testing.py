"""Add tenant-scoped forward testing tables.

Revision ID: 0002_phase7_forward_testing
Revises: 0001_initial
"""
from alembic import op
import sqlalchemy as sa

revision = "0002_phase7_forward_testing"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "v11_forward_test_runs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("user_id", sa.String(length=36), sa.ForeignKey("v11_users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("portfolio_id", sa.String(length=36), sa.ForeignKey("v11_portfolios.id", ondelete="CASCADE"), nullable=False),
        sa.Column("account_id", sa.String(length=36), sa.ForeignKey("v11_broker_accounts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(length=12), nullable=False, server_default="active"),
        sa.Column("symbols", sa.JSON(), nullable=False),
        sa.Column("initial_equity", sa.Float(), nullable=False),
        sa.Column("risk_per_trade_pct", sa.Float(), nullable=False),
        sa.Column("min_quality_score", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("commission_pct", sa.Float(), nullable=False, server_default="0.04"),
        sa.Column("slippage_bps", sa.Float(), nullable=False, server_default="2.0"),
        sa.Column("include_existing_signals", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("stopped_at", sa.DateTime(timezone=True)),
        sa.Column("realized_pnl", sa.Float(), nullable=False, server_default="0"),
        sa.Column("fees_paid", sa.Float(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("status IN ('active','stopping','stopped')"),
        sa.CheckConstraint("initial_equity > 0"),
        sa.CheckConstraint("risk_per_trade_pct > 0 AND risk_per_trade_pct <= 100"),
        sa.CheckConstraint("commission_pct >= 0 AND commission_pct <= 5"),
        sa.CheckConstraint("slippage_bps >= 0 AND slippage_bps <= 1000"),
    )
    op.create_index("ix_v11_forward_test_runs_user_id", "v11_forward_test_runs", ["user_id"])
    op.create_index("ix_v11_forward_test_runs_portfolio_id", "v11_forward_test_runs", ["portfolio_id"])
    op.create_index("idx_forward_runs_owner_status", "v11_forward_test_runs", ["user_id", "status"])

    op.create_table(
        "v11_forward_test_trades",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("run_id", sa.String(length=36), sa.ForeignKey("v11_forward_test_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.String(length=36), sa.ForeignKey("v11_users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("portfolio_id", sa.String(length=36), sa.ForeignKey("v11_portfolios.id", ondelete="CASCADE"), nullable=False),
        sa.Column("signal_id", sa.String(length=36), sa.ForeignKey("signals.id", ondelete="CASCADE"), nullable=False),
        sa.Column("symbol", sa.String(length=40), nullable=False),
        sa.Column("direction", sa.String(length=8), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="pending_entry"),
        sa.Column("quality_score", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("planned_entry", sa.Float(), nullable=False),
        sa.Column("actual_entry", sa.Float()),
        sa.Column("stop_loss", sa.Float(), nullable=False),
        sa.Column("tp1", sa.Float(), nullable=False),
        sa.Column("tp2", sa.Float(), nullable=False),
        sa.Column("tp3", sa.Float(), nullable=False),
        sa.Column("quantity", sa.Float(), nullable=False),
        sa.Column("remaining_quantity", sa.Float(), nullable=False),
        sa.Column("risk_cash", sa.Float(), nullable=False),
        sa.Column("realized_pnl", sa.Float(), nullable=False, server_default="0"),
        sa.Column("fees_paid", sa.Float(), nullable=False, server_default="0"),
        sa.Column("last_price", sa.Float()),
        sa.Column("last_event_time_ms", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("last_event_id", sa.String(length=80)),
        sa.Column("entry_time", sa.DateTime(timezone=True)),
        sa.Column("closed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("run_id", "signal_id", name="uq_forward_trade_run_signal"),
        sa.CheckConstraint("direction IN ('long','short')"),
        sa.CheckConstraint("status IN ('pending_entry','open','tp1_hit','tp2_hit','tp3_hit','stopped')"),
        sa.CheckConstraint("quantity > 0 AND remaining_quantity >= 0"),
        sa.CheckConstraint("planned_entry > 0 AND stop_loss > 0 AND tp1 > 0 AND tp2 > 0 AND tp3 > 0"),
    )
    op.create_index("idx_forward_trades_run_status", "v11_forward_test_trades", ["run_id", "status"])
    op.create_index("idx_forward_trades_user_created", "v11_forward_test_trades", ["user_id", "created_at"])
    op.create_index("ix_v11_forward_test_trades_user_id", "v11_forward_test_trades", ["user_id"])
    op.create_index("ix_v11_forward_test_trades_portfolio_id", "v11_forward_test_trades", ["portfolio_id"])
    op.create_index("ix_v11_forward_test_trades_symbol", "v11_forward_test_trades", ["symbol"])

    op.create_table(
        "v11_forward_test_events",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("trade_id", sa.String(length=36), sa.ForeignKey("v11_forward_test_trades.id", ondelete="CASCADE"), nullable=False),
        sa.Column("event_type", sa.String(length=40), nullable=False),
        sa.Column("market_price", sa.Float(), nullable=False),
        sa.Column("fill_price", sa.Float()),
        sa.Column("quantity", sa.Float(), nullable=False, server_default="0"),
        sa.Column("pnl", sa.Float(), nullable=False, server_default="0"),
        sa.Column("fee", sa.Float(), nullable=False, server_default="0"),
        sa.Column("event_time_ms", sa.BigInteger(), nullable=False),
        sa.Column("event_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("details_json", sa.JSON(), nullable=False),
    )
    op.create_index("ix_v11_forward_test_events_trade_id", "v11_forward_test_events", ["trade_id"])


def downgrade():
    op.drop_table("v11_forward_test_events")
    op.drop_table("v11_forward_test_trades")
    op.drop_table("v11_forward_test_runs")
