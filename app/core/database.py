"""
app/core/database.py
====================
Async SQLAlchemy engine, session factory, and FastAPI dependency.

Usage in a route:
    async def my_route(db: AsyncSession = Depends(get_db)):
        result = await db.execute(select(Company))

Usage in a Celery worker (sync context):
    with SyncSessionLocal() as session:
        session.query(Company).all()
"""

from __future__ import annotations

import contextlib
from collections.abc import AsyncGenerator, Generator
from typing import Any

import structlog
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool

from app.core.config import settings

logger = structlog.get_logger(__name__)

# =============================================================================
# Async engine
# =============================================================================

def _build_engine_kwargs() -> dict[str, Any]:
    """Build engine kwargs, disabling connection pooling in test mode."""
    base: dict[str, Any] = {
        "echo": settings.DATABASE_ECHO,
        "echo_pool": settings.DATABASE_ECHO,
        "future": True,
    }
    if settings.APP_ENV == "testing":
        # NullPool prevents issues with pytest-asyncio event loop teardown
        base["poolclass"] = NullPool
    else:
        base.update(
            {
                "pool_size": settings.DATABASE_POOL_SIZE,
                "max_overflow": settings.DATABASE_MAX_OVERFLOW,
                "pool_timeout": settings.DATABASE_POOL_TIMEOUT,
                "pool_recycle": settings.DATABASE_POOL_RECYCLE,
                "pool_pre_ping": True,     # verify connections before use
            }
        )
    return base


engine: AsyncEngine = create_async_engine(
    settings.database_url_str,
    **_build_engine_kwargs(),
)

# Session factory — use this everywhere via Depends(get_db)
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,   # avoid lazy-load errors after commit
)

# =============================================================================
# Sync engine (Alembic migrations + Celery workers)
# =============================================================================
try:
    from sqlalchemy import create_engine as _create_engine
    from sqlalchemy.orm import sessionmaker as _sessionmaker

    _sync_engine = _create_engine(
        settings.DATABASE_SYNC_URL,
        pool_size=5,
        max_overflow=2,
        pool_pre_ping=True,
        echo=settings.DATABASE_ECHO,
    )
    SyncSessionLocal: sessionmaker[Session] = _sessionmaker(
        bind=_sync_engine,
        autocommit=False,
        autoflush=False,
        expire_on_commit=False,
    )
except Exception:
    # psycopg2 may not be installed in pure-async environments
    SyncSessionLocal = None  # type: ignore[assignment]
    _sync_engine = None      # type: ignore[assignment]


# =============================================================================
# FastAPI dependency
# =============================================================================

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    Yield a database session per request.
    Commits on success, rolls back on exception, always closes.

    Use as a FastAPI dependency:
        async def route(db: AsyncSession = Depends(get_db)):
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


# =============================================================================
# Context managers (non-dependency usage)
# =============================================================================

@contextlib.asynccontextmanager
async def get_db_context() -> AsyncGenerator[AsyncSession, None]:
    """
    Async context manager for use outside of FastAPI (e.g. startup tasks).

    async with get_db_context() as db:
        await db.execute(...)
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


@contextlib.contextmanager
def get_sync_db_context() -> Generator[Session, None, None]:
    """
    Sync context manager for Celery tasks.

    with get_sync_db_context() as db:
        db.query(Company).all()
    """
    if SyncSessionLocal is None:
        raise RuntimeError("Sync DB session not available — psycopg2 not installed.")
    session = SyncSessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


# =============================================================================
# Health check
# =============================================================================

async def check_database_health() -> dict[str, Any]:
    """
    Returns DB connectivity status for the /health endpoint.
    """
    try:
        async with engine.connect() as conn:
            result = await conn.execute(text("SELECT 1"))
            row = result.scalar()
        return {"status": "healthy", "response": row}
    except Exception as exc:
        logger.error("database_health_check_failed", error=str(exc))
        return {"status": "unhealthy", "error": str(exc)}


# =============================================================================
# Engine lifecycle hooks (logging)
# =============================================================================

@event.listens_for(engine.sync_engine, "connect")
def on_connect(dbapi_connection: Any, connection_record: Any) -> None:
    logger.debug("db_connection_acquired")


@event.listens_for(engine.sync_engine, "checkout")
def on_checkout(
    dbapi_connection: Any,
    connection_record: Any,
    connection_proxy: Any,
) -> None:
    logger.debug("db_connection_checked_out")


# =============================================================================
# Convenience: get a raw async connection (for DDL / migrations in code)
# =============================================================================

@contextlib.asynccontextmanager
async def get_connection() -> AsyncGenerator[AsyncConnection, None]:
    """Low-level async connection for raw SQL / DDL statements."""
    async with engine.connect() as conn:
        yield conn


async def dispose_engine() -> None:
    """Gracefully close all connections. Call on app shutdown."""
    await engine.dispose()
    logger.info("database_engine_disposed")
