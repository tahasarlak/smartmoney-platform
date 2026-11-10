from logging.config import fileConfig
import os
from alembic import context
from sqlalchemy import engine_from_config, pool
from sqlalchemy.engine import make_url

from app.database import Base
from app import db_models  # noqa: F401 - register model metadata
from app import production_models  # noqa: F401 - register production safety models

config = context.config
if config.config_file_name:
    fileConfig(config.config_file_name)

raw = os.getenv("DIRECT_URL") or os.getenv("DATABASE_URL")
if not raw:
    raise RuntimeError("DIRECT_URL or DATABASE_URL is required for migrations")
url = make_url(raw)
if url.drivername in ("postgres", "postgresql"):
    url = url.set(drivername="postgresql+psycopg")
config.set_main_option("sqlalchemy.url", url.render_as_string(hide_password=False).replace("%", "%%"))
target_metadata = Base.metadata

def run_migrations_offline():
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()

def run_migrations_online():
    connectable = engine_from_config(
        config.get_section(config.config_ini_section),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        pool_pre_ping=True,
        connect_args={"connect_timeout": 20, "sslmode": "require"},
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()
    connectable.dispose()

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

