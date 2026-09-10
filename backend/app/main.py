"""FastAPI application: middleware, error mapping, router mounting."""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from prometheus_fastapi_instrumentator import Instrumentator
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.cors import CORSMiddleware

from app.api import chat, documents, health, provider_settings
from app.config import get_settings
from app.db import dispose_engine, init_schema, is_sqlite
from app.observability import configure_logging, get_logger, new_request_id, request_id_var
from app.services.errors import AppError
from app.services.provider import describe_provider, restore_saved_provider
from app.services.storage import close_storage
from app.workers.ingest import recover_interrupted_ingests

PROBLEM_JSON = "application/problem+json"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(settings.log_level, json_output=settings.environment != "local")
    log = get_logger("app.startup")

    # SQLite has no migration history, so its schema is created here. This is
    # what lets a fresh clone answer questions without any setup step.
    await init_schema()
    # A key saved in a previous run is reloaded so "connected" survives restarts.
    restored = restore_saved_provider()

    log.info(
        "startup",
        environment=settings.environment,
        database="sqlite" if is_sqlite() else "postgresql",
        storage="local" if settings.storage_is_local else "azure_blob",
        hybrid_retrieval=settings.retrieval_hybrid,
        answer_mode=describe_provider().mode,
    )
    # A document stranded by a crash or a reloader restart would otherwise sit at
    # "pending" forever, answering nothing. Kicked off in the background so a
    # large backlog does not delay the port opening.
    recovery = asyncio.create_task(_recover_ingests(log))

    if restored:
        log.info("startup.provider_restored", provider=restored)
    else:
        log.info(
            "startup.offline_mode",
            detail="No LLM key configured. Answers are quoted from the uploaded "
            "documents. Add a key in the UI to also get generated answers.",
        )
    try:
        yield
    finally:
        recovery.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await recovery
        await close_storage()
        await dispose_engine()
        log.info("shutdown")


async def _recover_ingests(log: Any) -> None:
    restarted = await recover_interrupted_ingests()
    if restarted:
        log.info("startup.ingests_recovered", documents=restarted)


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="ClauseCite API",
        version="0.1.0",
        summary="Ask questions across a set of contracts and get answers with "
        "citations that resolve to a highlighted passage in the source PDF.",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID"],
    )

    @app.middleware("http")
    async def request_context(
        request: Request, call_next: Callable[[Request], Awaitable[JSONResponse]]
    ) -> JSONResponse:
        # Honour an inbound id so a request can be followed across the frontend,
        # ingress, and this service.
        request_id = request.headers.get("x-request-id") or new_request_id()
        token = request_id_var.set(request_id)
        started = time.perf_counter()
        try:
            response = await call_next(request)
        finally:
            request_id_var.reset(token)
        response.headers["X-Request-ID"] = request_id
        duration_ms = int((time.perf_counter() - started) * 1000)
        if request.url.path not in {"/health", "/metrics"}:
            get_logger("app.request").info(
                "request",
                method=request.method,
                path=request.url.path,
                status=response.status_code,
                duration_ms=duration_ms,
                request_id=request_id,
            )
        return response

    @app.exception_handler(AppError)
    async def app_error_handler(_request: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status,
            media_type=PROBLEM_JSON,
            content={
                "type": exc.problem_type,
                "title": exc.title,
                "status": exc.status,
                "detail": exc.detail,
            },
        )

    @app.exception_handler(RequestValidationError)
    async def validation_handler(
        _request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            media_type=PROBLEM_JSON,
            content={
                "type": "/errors/validation",
                "title": "Request validation failed",
                "status": 422,
                "detail": "; ".join(
                    f"{'.'.join(str(p) for p in err['loc'][1:])}: {err['msg']}"
                    for err in exc.errors()
                )
                or "Invalid request.",
            },
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_error_handler(
        _request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        # Every error the API emits uses one shape, including framework 404s.
        return JSONResponse(
            status_code=exc.status_code,
            media_type=PROBLEM_JSON,
            content={
                "type": f"/errors/http-{exc.status_code}",
                "title": str(exc.detail),
                "status": exc.status_code,
                "detail": str(exc.detail),
            },
        )

    app.include_router(health.router)
    app.include_router(documents.router)
    app.include_router(chat.router)
    app.include_router(provider_settings.router)

    Instrumentator(
        excluded_handlers=["/metrics", "/health"],
        should_group_status_codes=False,
    ).instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)

    return app


app = create_app()
