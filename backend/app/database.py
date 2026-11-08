"""Lazy SQLAlchemy database layer for Neon PostgreSQL.

No network connection is opened at import time. Set DATABASE_URL for the
pooled runtime URL and DIRECT_URL for Alembic migrations.
"""
from __future__ import annotations
import os
from functools import lru_cache
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import DeclarativeBase, sessionmaker, Session

class Base(DeclarativeBase):
    pass

def _normalize_url(raw: str):
    url = make_url(raw)
    if url.drivername in ("postgres", "postgresql"):
        url = url.set(drivername="postgresql+psycopg")
    return url

@lru_cache(maxsize=1)
def get_engine():
    raw = os.getenv("DATABASE_URL") or os.getenv("DIRECT_URL")
    if not raw:
        raise RuntimeError("DATABASE_URL or DIRECT_URL must be configured")
    url = _normalize_url(raw)
    kwargs = {"pool_pre_ping": True, "pool_recycle": 1800}
    if url.get_backend_name() == "postgresql":
        kwargs.update(pool_size=int(os.getenv("DB_POOL_SIZE", "5")),
                      max_overflow=int(os.getenv("DB_MAX_OVERFLOW", "5")),
                      connect_args={
                          "connect_timeout": 15,
                          "sslmode": "require",
                          # Neon pooled endpoints use PgBouncer transaction pooling.
                          # Disable server-side prepared statements for compatibility.
                          "prepare_threshold": None,
                      })
    return create_engine(url, **kwargs)

@lru_cache(maxsize=1)
def get_session_factory():
    return sessionmaker(bind=get_engine(), autoflush=False, expire_on_commit=False, class_=Session)

def session_scope():
    """Context manager yielding a transaction-scoped Session."""
    from contextlib import contextmanager
    @contextmanager
    def _scope():
        session = get_session_factory()()
        try:
            with session.begin():
                yield session
        finally:
            session.close()
    return _scope()

def get_db():
    db = get_session_factory()()
    try:
        yield db
    finally:
        db.close()

def dispose_engine():
    if get_engine.cache_info().currsize:
        get_engine().dispose()
        get_engine.cache_clear()
        get_session_factory.cache_clear()
