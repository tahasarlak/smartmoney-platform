"""Initial clean PostgreSQL schema for SmartMoney V11.

revision: 0001_initial
"""
from alembic import op
from app.database import Base
from app import db_models  # noqa: F401

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None

def upgrade():
    # Keep this historical baseline migration frozen. New models must be
    # introduced by later versioned migrations, never implicitly here.
    baseline_names = {
        "v11_users", "v11_sessions", "v11_portfolios",
        "v11_broker_accounts", "v11_paper_orders",
        "v11_audit_events", "v11_backtest_runs",
        "market_prices", "market_watchlist", "signals", "signal_events",
    }
    baseline_tables = [
        table for table in Base.metadata.sorted_tables
        if table.name in baseline_names
    ]
    Base.metadata.create_all(bind=op.get_bind(), tables=baseline_tables)

def downgrade():
    baseline_names = {
        "v11_users", "v11_sessions", "v11_portfolios",
        "v11_broker_accounts", "v11_paper_orders",
        "v11_audit_events", "v11_backtest_runs",
        "market_prices", "market_watchlist", "signals", "signal_events",
    }
    baseline_tables = [
        table for table in Base.metadata.sorted_tables
        if table.name in baseline_names
    ]
    Base.metadata.drop_all(bind=op.get_bind(), tables=list(reversed(baseline_tables)))
