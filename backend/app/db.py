"""Async engine, session dependency, and first-run schema creation."""

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import get_settings

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def is_sqlite() -> bool:
    return get_settings().database_url.startswith("sqlite")


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        settings = get_settings()
        kwargs: dict[str, Any] = {"pool_pre_ping": True, "echo": False}

        if settings.database_url.startswith("sqlite"):
            # SQLite has no server and no connection pool to size; passing
            # pool_size here raises rather than being ignored.
            _ensure_sqlite_directory(settings.database_url)
        else:
            kwargs["pool_size"] = settings.db_pool_size
            kwargs["max_overflow"] = settings.db_max_overflow

        _engine = create_async_engine(settings.database_url, **kwargs)

        if settings.database_url.startswith("sqlite"):
            # SQLite ignores ON DELETE CASCADE unless foreign keys are enabled,
            # per connection. Without this, deleting a document silently orphans
            # its chunks and they keep showing up in retrieval.
            @event.listens_for(_engine.sync_engine, "connect")
            def _configure_sqlite(dbapi_connection: Any, _record: Any) -> None:
                cursor = dbapi_connection.cursor()
                cursor.execute("PRAGMA foreign_keys=ON")
                # WAL lets the ingest background task write while a request reads.
                cursor.execute("PRAGMA journal_mode=WAL")
                # SQLite allows one writer at a time and, by default, fails
                # instantly when it cannot get the lock. Ingesting a document
                # while another request writes is routine here, so wait for the
                # lock instead of surfacing "database is locked" as a 500.
                cursor.execute("PRAGMA busy_timeout=10000")
                cursor.close()

    return _engine


def _ensure_sqlite_directory(url: str) -> None:
    """Create the parent directory of a SQLite file so the first run works."""
    path_part = url.split("///", 1)[-1].split("?", 1)[0]
    if not path_part or path_part == ":memory:":
        return
    parent = Path(path_part).expanduser().parent
    if parent and not parent.exists():
        parent.mkdir(parents=True, exist_ok=True)


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    global _sessionmaker
    if _sessionmaker is None:
        _sessionmaker = async_sessionmaker(
            get_engine(), expire_on_commit=False, autoflush=False
        )
    return _sessionmaker


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: one session per request, rolled back on error."""
    async with get_sessionmaker()() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


async def init_schema() -> None:
    """Create tables if they are missing.

    Alembic owns the PostgreSQL schema — it is the only place the HNSW and GIN
    indexes are declared, and running `create_all` there would produce a schema
    that no migration knows about. SQLite has no migration history and no
    pgvector, so its schema is created straight from the ORM metadata; this is
    what makes a first run work with nothing installed.
    """
    if not is_sqlite():
        return

    from app.models import Base

    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def ping() -> None:
    async with get_sessionmaker()() as session:
        await session.execute(text("SELECT 1"))


async def dispose_engine() -> None:
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _sessionmaker = None
