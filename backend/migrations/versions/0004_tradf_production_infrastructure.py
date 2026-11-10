"""TRADF production safety infrastructure (testnet only).

Revision ID: 0004_tradf_production_infrastructure
Revises: 0003_phase9_paper_execution
"""
from alembic import op
import sqlalchemy as sa

revision = "0004_tradf_production_infrastructure"
down_revision = "0003_phase9_paper_execution"
branch_labels = None
depends_on = None

def upgrade():
    op.execute(
        "ALTER TABLE alembic_version "
        "ALTER COLUMN version_num TYPE VARCHAR(128)"
    )
    op.create_table(
        "tradf_exchange_credentials",
        sa.Column("id",sa.String(36),primary_key=True),
        sa.Column("user_id",sa.String(36),sa.ForeignKey("v11_users.id",ondelete="CASCADE"),nullable=False),
        sa.Column("portfolio_id",sa.String(36),sa.ForeignKey("v11_portfolios.id",ondelete="CASCADE"),nullable=False),
        sa.Column("provider",sa.String(24),nullable=False,server_default="binance_spot_testnet"),
        sa.Column("label",sa.String(80),nullable=False),
        sa.Column("encrypted_api_key",sa.Text(),nullable=False),
        sa.Column("encrypted_api_secret",sa.Text(),nullable=False),
        sa.Column("key_fingerprint",sa.String(16),nullable=False),
        sa.Column("status",sa.String(16),nullable=False,server_default="active"),
        sa.Column("last_verified_at",sa.DateTime(timezone=True)),
        sa.Column("created_at",sa.DateTime(timezone=True),nullable=False,server_default=sa.func.now()),
        sa.Column("updated_at",sa.DateTime(timezone=True),nullable=False,server_default=sa.func.now()),
    )
    op.create_index("ix_tradf_exchange_credentials_user_id","tradf_exchange_credentials",["user_id"])
    op.create_index("ix_tradf_exchange_credentials_portfolio_id","tradf_exchange_credentials",["portfolio_id"])

    op.create_table(
        "tradf_exchange_orders",
        sa.Column("id",sa.String(36),primary_key=True),
        sa.Column("user_id",sa.String(36),sa.ForeignKey("v11_users.id",ondelete="CASCADE"),nullable=False),
        sa.Column("portfolio_id",sa.String(36),sa.ForeignKey("v11_portfolios.id",ondelete="CASCADE"),nullable=False),
        sa.Column("credential_id",sa.String(36),sa.ForeignKey("tradf_exchange_credentials.id",ondelete="RESTRICT"),nullable=False),
        sa.Column("provider",sa.String(24),nullable=False,server_default="binance_spot_testnet"),
        sa.Column("symbol",sa.String(30),nullable=False),
        sa.Column("side",sa.String(4),nullable=False),
        sa.Column("order_type",sa.String(12),nullable=False,server_default="LIMIT"),
        sa.Column("quantity",sa.String(40),nullable=False),
        sa.Column("price",sa.String(40),nullable=False),
        sa.Column("client_order_id",sa.String(36),nullable=False),
        sa.Column("exchange_order_id",sa.String(40)),
        sa.Column("status",sa.String(24),nullable=False,server_default="SUBMITTING"),
        sa.Column("response_json",sa.JSON(),nullable=False,server_default=sa.text("'{}'")),
        sa.Column("last_error_code",sa.String(80)),
        sa.Column("created_at",sa.DateTime(timezone=True),nullable=False,server_default=sa.func.now()),
        sa.Column("updated_at",sa.DateTime(timezone=True),nullable=False,server_default=sa.func.now()),
        sa.UniqueConstraint("user_id","client_order_id",name="uq_tradf_exchange_user_client_order"),
    )
    op.create_index("ix_tradf_exchange_orders_user_id","tradf_exchange_orders",["user_id"])
    op.create_index("ix_tradf_exchange_orders_portfolio_id","tradf_exchange_orders",["portfolio_id"])
    op.create_index("ix_tradf_exchange_orders_owner_status","tradf_exchange_orders",["user_id","status"])

    op.create_table(
        "tradf_global_kill_switch",
        sa.Column("id",sa.Integer(),primary_key=True),
        sa.Column("enabled",sa.Boolean(),nullable=False,server_default=sa.true()),
        sa.Column("reason",sa.String(240),nullable=False,server_default="Safe default"),
        sa.Column("activated_at",sa.DateTime(timezone=True)),
        sa.Column("updated_at",sa.DateTime(timezone=True),nullable=False,server_default=sa.func.now()),
        sa.CheckConstraint("id = 1",name="ck_tradf_global_kill_switch_singleton"),
    )
    op.execute("INSERT INTO tradf_global_kill_switch (id, enabled, reason) VALUES (1, TRUE, 'Fail-closed initial state')")

    op.create_table(
        "tradf_user_kill_switches",
        sa.Column("user_id",sa.String(36),sa.ForeignKey("v11_users.id",ondelete="CASCADE"),primary_key=True),
        sa.Column("enabled",sa.Boolean(),nullable=False,server_default=sa.true()),
        sa.Column("reason",sa.String(240),nullable=False,server_default="Default safe state"),
        sa.Column("activated_at",sa.DateTime(timezone=True)),
        sa.Column("updated_at",sa.DateTime(timezone=True),nullable=False,server_default=sa.func.now()),
    )

    op.create_table(
        "tradf_scheduler_jobs",
        sa.Column("id",sa.String(36),primary_key=True),
        sa.Column("user_id",sa.String(36),sa.ForeignKey("v11_users.id",ondelete="CASCADE"),nullable=False),
        sa.Column("portfolio_id",sa.String(36),sa.ForeignKey("v11_portfolios.id",ondelete="CASCADE"),nullable=False),
        sa.Column("job_type",sa.String(40),nullable=False),
        sa.Column("interval_seconds",sa.Integer(),nullable=False,server_default="900"),
        sa.Column("enabled",sa.Boolean(),nullable=False,server_default=sa.true()),
        sa.Column("next_run_at",sa.DateTime(timezone=True),nullable=False),
        sa.Column("lease_owner",sa.String(80)),
        sa.Column("lease_until",sa.DateTime(timezone=True)),
        sa.Column("last_run_at",sa.DateTime(timezone=True)),
        sa.Column("last_status",sa.String(24)),
        sa.Column("last_error",sa.String(240)),
        sa.Column("created_at",sa.DateTime(timezone=True),nullable=False,server_default=sa.func.now()),
        sa.Column("updated_at",sa.DateTime(timezone=True),nullable=False,server_default=sa.func.now()),
        sa.CheckConstraint("interval_seconds BETWEEN 300 AND 3600",name="ck_tradf_scheduler_interval"),
        sa.UniqueConstraint("user_id","portfolio_id","job_type",name="uq_tradf_scheduler_owner_portfolio_type"),
    )
    op.create_index("ix_tradf_scheduler_jobs_user_id","tradf_scheduler_jobs",["user_id"])
    op.create_index("ix_tradf_scheduler_jobs_portfolio_id","tradf_scheduler_jobs",["portfolio_id"])
    op.create_index("ix_tradf_scheduler_due","tradf_scheduler_jobs",["enabled","next_run_at","lease_until"])

    op.create_table(
        "tradf_paper_burnin_samples",
        sa.Column("id",sa.Integer(),primary_key=True,autoincrement=True),
        sa.Column("job_id",sa.String(36),sa.ForeignKey("tradf_scheduler_jobs.id",ondelete="CASCADE"),nullable=False),
        sa.Column("user_id",sa.String(36),sa.ForeignKey("v11_users.id",ondelete="CASCADE"),nullable=False),
        sa.Column("portfolio_id",sa.String(36),sa.ForeignKey("v11_portfolios.id",ondelete="CASCADE"),nullable=False),
        sa.Column("scheduled_for",sa.DateTime(timezone=True),nullable=False),
        sa.Column("sampled_at",sa.DateTime(timezone=True),nullable=False,server_default=sa.func.now()),
        sa.Column("metrics_json",sa.JSON(),nullable=False,server_default=sa.text("'{}'")),
        sa.UniqueConstraint("job_id","scheduled_for",name="uq_tradf_burnin_job_slot"),
    )
    op.create_index("ix_tradf_paper_burnin_samples_job_id","tradf_paper_burnin_samples",["job_id"])
    op.create_index("ix_tradf_paper_burnin_samples_user_id","tradf_paper_burnin_samples",["user_id"])
    op.create_index("ix_tradf_paper_burnin_samples_portfolio_id","tradf_paper_burnin_samples",["portfolio_id"])

def downgrade():
    op.drop_table("tradf_paper_burnin_samples")
    op.drop_table("tradf_scheduler_jobs")
    op.drop_table("tradf_user_kill_switches")
    op.drop_table("tradf_global_kill_switch")
    op.drop_table("tradf_exchange_orders")
    op.drop_table("tradf_exchange_credentials")
