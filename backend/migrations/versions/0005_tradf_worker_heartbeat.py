"""Add TRADF background worker heartbeat.

Revision ID: 0005_tradf_worker_heartbeat
Revises: 0004_tradf_production_infrastructure
"""
from alembic import op
import sqlalchemy as sa

revision = "0005_tradf_worker_heartbeat"
down_revision = "0004_tradf_production_infrastructure"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "tradf_worker_heartbeats",
        sa.Column("worker_id", sa.String(120), primary_key=True),
        sa.Column("hostname", sa.String(120), nullable=False),
        sa.Column("process_id", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_job_at", sa.DateTime(timezone=True)),
        sa.Column("status", sa.String(20), nullable=False, server_default="running"),
    )
    op.create_index(
        "ix_tradf_worker_heartbeats_heartbeat_at",
        "tradf_worker_heartbeats",
        ["heartbeat_at"],
    )


def downgrade():
    op.drop_index("ix_tradf_worker_heartbeats_heartbeat_at", table_name="tradf_worker_heartbeats")
    op.drop_table("tradf_worker_heartbeats")
