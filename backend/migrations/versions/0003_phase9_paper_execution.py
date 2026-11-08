"""Add persistent, tenant-scoped paper execution trades and event journal.

Revision ID: 0003_phase9_paper_execution
Revises: 0002_phase7_forward_testing
"""
from alembic import op
import sqlalchemy as sa

revision = "0003_phase9_paper_execution"
down_revision = "0002_phase7_forward_testing"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "v11_execution_trades",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("v11_users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("portfolio_id", sa.String(36), sa.ForeignKey("v11_portfolios.id", ondelete="CASCADE"), nullable=False),
        sa.Column("account_id", sa.String(36), sa.ForeignKey("v11_broker_accounts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("broker", sa.String(20), nullable=False),
        sa.Column("idempotency_key", sa.String(80), nullable=False),
        sa.Column("symbol", sa.String(40), nullable=False),
        sa.Column("side", sa.String(8), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending_entry"),
        sa.Column("planned_entry", sa.Float(), nullable=False),
        sa.Column("avg_entry_price", sa.Float()),
        sa.Column("stop_loss", sa.Float(), nullable=False),
        sa.Column("initial_stop_loss", sa.Float(), nullable=False),
        sa.Column("tp1", sa.Float(), nullable=False),
        sa.Column("tp2", sa.Float(), nullable=False),
        sa.Column("tp3", sa.Float(), nullable=False),
        sa.Column("quantity", sa.Float(), nullable=False),
        sa.Column("remaining_quantity", sa.Float(), nullable=False),
        sa.Column("tp1_fraction", sa.Float(), nullable=False, server_default="0.5"),
        sa.Column("tp2_fraction", sa.Float(), nullable=False, server_default="0.3"),
        sa.Column("tp3_fraction", sa.Float(), nullable=False, server_default="0.2"),
        sa.Column("tp1_hit", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("tp2_hit", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("tp3_hit", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("move_stop_to_breakeven_after_tp1", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("trailing_stop_pct", sa.Float()),
        sa.Column("high_water", sa.Float()),
        sa.Column("low_water", sa.Float()),
        sa.Column("commission_pct", sa.Float(), nullable=False, server_default="0.04"),
        sa.Column("slippage_bps", sa.Float(), nullable=False, server_default="2.0"),
        sa.Column("realized_pnl", sa.Float(), nullable=False, server_default="0"),
        sa.Column("fees_paid", sa.Float(), nullable=False, server_default="0"),
        sa.Column("last_price", sa.Float()),
        sa.Column("last_event_time_ms", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("last_event_id", sa.String(80)),
        sa.Column("entry_filled_at_ms", sa.BigInteger()),
        sa.Column("closed_at_ms", sa.BigInteger()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("user_id", "idempotency_key", name="uq_execution_user_idempotency"),
        sa.CheckConstraint("broker IN ('binance','mt5')"),
        sa.CheckConstraint("side IN ('long','short')"),
        sa.CheckConstraint("status IN ('pending_entry','open','partially_closed','closed','cancelled')"),
        sa.CheckConstraint("quantity > 0 AND remaining_quantity >= 0 AND remaining_quantity <= quantity"),
        sa.CheckConstraint("planned_entry > 0 AND stop_loss > 0 AND tp1 > 0 AND tp2 > 0 AND tp3 > 0"),
        sa.CheckConstraint("commission_pct >= 0 AND commission_pct <= 5"),
        sa.CheckConstraint("slippage_bps >= 0 AND slippage_bps <= 1000"),
        sa.CheckConstraint("tp1_fraction > 0 AND tp2_fraction > 0 AND tp3_fraction > 0 AND tp1_fraction + tp2_fraction + tp3_fraction BETWEEN 0.999999 AND 1.000001"),
        sa.CheckConstraint("trailing_stop_pct IS NULL OR (trailing_stop_pct > 0 AND trailing_stop_pct <= 20)"),
    )
    op.create_index("ix_v11_execution_trades_user_id", "v11_execution_trades", ["user_id"])
    op.create_index("ix_v11_execution_trades_portfolio_id", "v11_execution_trades", ["portfolio_id"])
    op.create_index("ix_v11_execution_trades_symbol", "v11_execution_trades", ["symbol"])
    op.create_index("idx_execution_portfolio_status", "v11_execution_trades", ["portfolio_id", "status"])
    op.create_index("idx_execution_user_created", "v11_execution_trades", ["user_id", "created_at"])

    op.create_table(
        "v11_execution_events",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("trade_id", sa.String(36), sa.ForeignKey("v11_execution_trades.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_event_id", sa.String(80), nullable=False),
        sa.Column("sequence_no", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("event_type", sa.String(40), nullable=False),
        sa.Column("market_price", sa.Float(), nullable=False),
        sa.Column("fill_price", sa.Float()),
        sa.Column("quantity", sa.Float(), nullable=False, server_default="0"),
        sa.Column("pnl", sa.Float(), nullable=False, server_default="0"),
        sa.Column("fee", sa.Float(), nullable=False, server_default="0"),
        sa.Column("event_time_ms", sa.BigInteger(), nullable=False),
        sa.Column("event_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("details_json", sa.JSON(), nullable=False),
        sa.UniqueConstraint("trade_id", "source_event_id", "sequence_no", name="uq_execution_event_source_sequence"),
    )
    op.create_index("ix_v11_execution_events_trade_id", "v11_execution_events", ["trade_id"])
    op.create_index("idx_execution_events_trade_time", "v11_execution_events", ["trade_id", "event_time_ms"])


def downgrade():
    op.drop_table("v11_execution_events")
    op.drop_table("v11_execution_trades")
