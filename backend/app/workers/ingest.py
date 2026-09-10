"""Background ingestion.

Runs via FastAPI `BackgroundTasks`, which is sufficient while ingestion is a
single-digit number of seconds and the API runs one replica.

**Migrate to a real queue** (Azure Storage Queue + a worker container) when any of
these becomes true:
  * ingestion exceeds ~60s, so an HTTP worker is tied up too long;
  * retries must survive a process restart;
  * the API scales past one replica, at which point "which replica is ingesting
    this?" stops having an answer.

Recovery is deliberately delete-and-restart rather than resume-from-halfway.
Resumption requires tracking which chunks were embedded, which batch failed, and
whether a partial write left a gap in `chunk_index`. Re-ingesting a 40-page
contract costs about ten seconds and a fraction of a cent, and it cannot leave a
document half-indexed — a state in which the app answers confidently from half a
contract, which is worse than not answering at all.

Because the task lives in the process, anything that kills the process mid-ingest
— a crash, a deploy, or the dev-server reloader firing — strands a document in
`pending` or `processing` where nothing will ever pick it up again. The user sees
a document that never finishes and gets no answers from it. `recover_interrupted_ingests`
runs at startup and restarts exactly those.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_sessionmaker
from app.models import Chunk, Document
from app.observability import get_logger, ingest_chunks, ingest_documents, ingest_duration
from app.services.chunk import ChunkDraft, chunk_document
from app.services.embed import embed_texts
from app.services.errors import AppError
from app.services.extract import extract_document
from app.services.storage import get_storage

log = get_logger(__name__)


async def recover_interrupted_ingests() -> int:
    """Re-run ingestion for documents left mid-flight by a previous process.

    Anything still `pending` or `processing` at startup cannot be in flight —
    the only thing that ingests is this process, and it has just started. So the
    state is a leftover, and re-running is safe: `_replace_chunks` deletes any
    partial rows first.

    Returns the number restarted. Never raises: a database that is not ready yet
    must not stop the app from serving.
    """
    try:
        sessionmaker = get_sessionmaker()
        async with sessionmaker() as session:
            stranded = list(
                (
                    await session.execute(
                        select(Document.id, Document.filename).where(
                            Document.status.in_(("pending", "processing"))
                        )
                    )
                ).all()
            )
    except Exception:  # startup must survive a slow or absent database
        log.exception("ingest.recovery_query_failed")
        return 0

    for document_id, filename in stranded:
        log.info("ingest.recovering", document_id=str(document_id), filename=filename)
        # Sequential rather than gathered: recovery is a background chore and
        # should not compete with live requests for the connection pool.
        await ingest_document(document_id)

    return len(stranded)


async def ingest_document(document_id: uuid.UUID) -> None:
    """Entry point for the background task. Never raises — it records failure."""
    sessionmaker = get_sessionmaker()
    started = time.perf_counter()
    status = "failed"
    chunk_total = 0

    try:
        async with sessionmaker() as session:
            document = await session.get(Document, document_id)
            if document is None:
                log.warning("ingest.document_missing", document_id=str(document_id))
                return
            document.status = "processing"
            document.error_message = None
            await session.commit()
            blob_path = document.blob_path
            filename = document.filename

        chunk_total = await _run_pipeline(sessionmaker, document_id, blob_path)
        status = "ready"
        log.info(
            "ingest.completed",
            document_id=str(document_id),
            filename=filename,
            chunks=chunk_total,
            duration_ms=int((time.perf_counter() - started) * 1000),
        )

    except AppError as exc:
        await _mark_failed(sessionmaker, document_id, exc.detail)
        log.warning(
            "ingest.rejected",
            document_id=str(document_id),
            reason=exc.problem_type,
            detail=exc.detail,
        )
    except Exception as exc:
        await _mark_failed(sessionmaker, document_id, f"Ingestion failed: {exc}")
        log.exception("ingest.failed", document_id=str(document_id))
    finally:
        ingest_duration.labels(status=status).observe(time.perf_counter() - started)
        ingest_documents.labels(status=status).inc()
        if status == "ready":
            ingest_chunks.observe(chunk_total)


async def _run_pipeline(
    sessionmaker: object, document_id: uuid.UUID, blob_path: str
) -> int:
    settings = get_settings()
    storage = get_storage()

    pdf_bytes = await storage.download(blob_path)
    extracted = extract_document(pdf_bytes, min_chars_per_page=settings.min_chars_per_page)
    drafts = chunk_document(
        extracted,
        target_tokens=settings.chunk_target_tokens,
        max_tokens=settings.chunk_max_tokens,
        overlap_tokens=settings.chunk_overlap_tokens,
    )
    if not drafts:
        from app.services.errors import UnsupportedDocumentError

        raise UnsupportedDocumentError(
            "No text could be chunked from this document.",
            problem_type="/errors/unsupported-document",
            title="Nothing to index",
        )

    # The section path is embedded but not stored: a clause reading "ninety (90)
    # days" retrieves poorly on its own and well under "3.2 Notice Period".
    vectors = await embed_texts([draft.embed_text for draft in drafts])

    async with sessionmaker() as session:  # type: ignore[operator]
        await _replace_chunks(session, document_id, drafts, vectors)
        document = await session.get(Document, document_id)
        if document is None:  # deleted mid-ingest
            await session.rollback()
            return 0
        document.page_count = extracted.page_count
        document.status = "ready"
        document.processed_at = datetime.now(UTC)
        document.error_message = None
        # One commit flips status to 'ready' alongside the chunk rows, so a reader
        # never sees a 'ready' document with no chunks.
        await session.commit()

    return len(drafts)


async def _replace_chunks(
    session: AsyncSession,
    document_id: uuid.UUID,
    drafts: Sequence[ChunkDraft],
    vectors: list[list[float]],
) -> None:
    await session.execute(delete(Chunk).where(Chunk.document_id == document_id))
    session.add_all(
        [
            Chunk(
                id=draft.id,
                document_id=document_id,
                chunk_index=draft.chunk_index,
                content=draft.content,
                token_count=draft.token_count,
                page_start=draft.page_start,
                page_end=draft.page_end,
                bbox=draft.bbox,
                section_path=draft.section_path,
                embedding=vector,
            )
            for draft, vector in zip(drafts, vectors, strict=True)
        ]
    )


async def _mark_failed(sessionmaker: object, document_id: uuid.UUID, message: str) -> None:
    try:
        async with sessionmaker() as session:  # type: ignore[operator]
            document = await session.get(Document, document_id)
            if document is None:
                return
            document.status = "failed"
            # Truncated: an exception repr can be enormous and this string is
            # rendered verbatim in the UI.
            document.error_message = message[:1000]
            await session.commit()
    except Exception:  # pragma: no cover - the DB itself is the failure
        log.exception("ingest.mark_failed_failed", document_id=str(document_id))


async def count_chunks(session: AsyncSession, document_id: uuid.UUID) -> int:
    from sqlalchemy import func

    result = await session.execute(
        select(func.count()).select_from(Chunk).where(Chunk.document_id == document_id)
    )
    return int(result.scalar() or 0)
