"""Liveness and readiness.

The split matters operationally. `/health` is what Container Apps probes, and it
checks nothing but "this process is running" — if it verified the database, a
thirty-second Postgres blip would make the platform restart every replica, turning
a brief dependency outage into a full outage. `/ready` does check dependencies and
is what CI smoke tests and humans use.
"""

from __future__ import annotations

from fastapi import APIRouter, Response, status
from sqlalchemy import text

from app.db import get_sessionmaker, is_sqlite
from app.observability import get_logger
from app.schemas import ReadyCheck
from app.services.provider import describe_provider, get_provider
from app.services.storage import get_storage

router = APIRouter(tags=["health"])
log = get_logger(__name__)


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready", response_model=ReadyCheck)
async def ready(response: Response) -> ReadyCheck:
    checks: dict[str, str] = {}

    try:
        async with get_sessionmaker()() as session:
            await session.execute(text("SELECT 1"))
            if is_sqlite():
                # SQLite needs no extension; the equivalent readiness question is
                # whether the schema was created, which init_schema guarantees.
                await session.execute(text("SELECT 1 FROM documents LIMIT 1"))
                checks["database"] = "ok (sqlite)"
            else:
                # A working connection is not the same as a usable schema: without
                # the extension, every query fails at retrieval time instead of here.
                extension = (
                    await session.execute(
                        text("SELECT 1 FROM pg_extension WHERE extname = 'vector'")
                    )
                ).scalar()
                checks["database"] = "ok" if extension else "missing pgvector extension"
    except Exception as exc:
        checks["database"] = f"error: {type(exc).__name__}"

    try:
        await get_storage().healthcheck()
        checks["storage"] = "ok"
    except Exception as exc:
        checks["storage"] = f"error: {type(exc).__name__}"

    description = describe_provider()
    if description.mode == "offline":
        # No key configured is a supported steady state, not a degraded one:
        # answers come from the uploaded documents alone.
        checks["ai_provider"] = "ok (offline — documents only)"
    else:
        try:
            await get_provider().healthcheck()
            checks["ai_provider"] = f"ok ({description.provider_name})"
        except Exception as exc:
            checks["ai_provider"] = f"error: {type(exc).__name__}"

    healthy = all(value.startswith("ok") for value in checks.values())
    if not healthy:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        log.warning("ready.degraded", checks=checks)
    return ReadyCheck(status="ready" if healthy else "degraded", checks=checks)
