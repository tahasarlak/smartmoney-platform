"""Persist per-symbol Forex tick freshness for safe paper readiness.

Revision ID: 0008_forex_worker_symbol_ticks
Revises: 0007_forex_intraday_paper
"""
from alembic import op
import sqlalchemy as sa

revision = "0008_forex_worker_symbol_ticks"
down_revision = "0007_forex_intraday_paper"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "tradf_forex_worker_state",
        sa.Column(
            "last_tick_by_symbol",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
    )


def downgrade():
    op.drop_column("tradf_forex_worker_state", "last_tick_by_symbol")
