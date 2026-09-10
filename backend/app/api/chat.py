"""Question answering over documents, streamed as Server-Sent Events.

Streaming is one-directional, so SSE beats WebSockets here: it is plain HTTP, it
passes through proxies and Container Apps ingress untouched, and the browser
reconnects on its own.

Event sequence:

    : open                      comment, flushes headers immediately
    event: sources              every source supplied to the model, upfront
    event: token                repeated, as text arrives
    event: citations            only the sources the answer actually cited
    event: done                 message id, latency, token counts
    event: error                terminal; replaces citations/done

`sources` is sent before generation so a `[2]` chip is clickable the instant it
appears mid-stream, rather than only once the answer finishes. `citations` then
narrows that set to what was cited and is what gets persisted.
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_session, get_sessionmaker
from app.models import Conversation, Message
from app.observability import (
    citations_per_answer,
    get_logger,
    no_answer_total,
    query_duration,
    retrieval_top_score,
    tokens_total,
    unresolved_citations,
)
from app.schemas import (
    ChatRequest,
    Citation,
    ConversationOut,
    ConversationSummary,
    MessageOut,
)
from app.services import generate as gen
from app.services.embed import embed_query
from app.services.errors import AppError, NotFoundError, ProviderError
from app.services.provider import MockProvider, describe_provider
from app.services.retrieve import RetrievedChunk, assemble_context, retrieve

router = APIRouter(prefix="/api", tags=["chat"])
log = get_logger(__name__)

_SSE_HEADERS = {
    "Cache-Control": "no-cache, no-transform",
    "Connection": "keep-alive",
    # nginx buffers proxied responses by default, which would hold the whole
    # answer back and make streaming pointless.
    "X-Accel-Buffering": "no",
}


def _sse(event: str, data: object) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


@router.post("/chat")
async def ask(request: ChatRequest, http_request: Request) -> StreamingResponse:
    return StreamingResponse(
        _answer_stream(request, http_request),
        media_type="text/event-stream",
        headers=_SSE_HEADERS,
    )


async def _answer_stream(
    request: ChatRequest, http_request: Request
) -> AsyncIterator[str]:
    settings = get_settings()
    sessionmaker = get_sessionmaker()
    started = time.perf_counter()

    yield ": open\n\n"

    try:
        # A session obtained via Depends() is closed before a StreamingResponse
        # body runs, so sessions are opened explicitly here. They are also kept
        # short: holding a pooled connection open across a multi-second LLM
        # stream is how a 5-connection pool becomes an outage.
        async with sessionmaker() as session:
            conversation = await _get_or_create_conversation(
                session, request.conversation_id, request.question
            )
            history = await _load_history(session, conversation.id, settings.history_messages)
            session.add(
                Message(conversation_id=conversation.id, role="user", content=request.question)
            )
            await session.commit()
            conversation_id = conversation.id

        stage = time.perf_counter()
        embedding = await embed_query(request.question)
        query_duration.labels(stage="embed").observe(time.perf_counter() - stage)

        stage = time.perf_counter()
        async with sessionmaker() as session:
            chunks = await retrieve(
                session,
                question=request.question,
                embedding=embedding,
                document_ids=request.document_ids,
            )
        query_duration.labels(stage="retrieve").observe(time.perf_counter() - stage)

        if chunks:
            retrieval_top_score.observe(chunks[0].score)

        numbered_sources, included = assemble_context(chunks)

        provider_description = describe_provider()
        llm_active = gen.llm_is_active()
        answer_mode = "documents_and_llm" if llm_active else "documents_only"
        model_label = provider_description.model

        if not included and not llm_active:
            # Nothing retrieved and no model to fall back on. Saying so is the
            # only honest option — inventing an answer is the failure this
            # product exists to prevent.
            async for event in _emit_no_sources(
                sessionmaker, conversation_id, started, answer_mode
            ):
                yield event
            return

        if included:
            yield _sse(
                "sources",
                {"sources": [_source_payload(c, i) for i, c in enumerate(included, 1)]},
            )
        else:
            # LLM mode with no matching documents: answer from general knowledge,
            # clearly labelled. The empty `sources` event tells the UI there is
            # nothing to cite so it renders the unsourced state rather than
            # waiting for chips that will never arrive.
            yield _sse("sources", {"sources": []})

        stage = time.perf_counter()
        parts: list[str] = []
        prompt_tokens: int | None = None
        completion_tokens: int | None = None
        degraded: str | None = None

        def new_stream(provider: object | None = None) -> object:
            if included:
                return gen.stream_answer(
                    question=request.question,
                    history=history,
                    numbered_sources=numbered_sources,
                    history_limit=settings.history_messages,
                    provider=provider,  # type: ignore[arg-type]
                )
            return gen.stream_without_sources(
                question=request.question,
                history=history,
                history_limit=settings.history_messages,
                provider=provider,  # type: ignore[arg-type]
            )

        async def pump(stream: object) -> AsyncIterator[str]:
            """Forward one provider stream as SSE, recording text and usage."""
            nonlocal prompt_tokens, completion_tokens
            async for delta in stream:  # type: ignore[attr-defined]
                if await http_request.is_disconnected():
                    # The user navigated away. Stop paying for tokens nobody reads.
                    log.info(
                        "chat.client_disconnected", conversation_id=str(conversation_id)
                    )
                    return
                if delta.text:
                    parts.append(delta.text)
                    yield _sse("token", {"text": delta.text})
                if delta.prompt_tokens is not None:
                    prompt_tokens = delta.prompt_tokens
                if delta.completion_tokens is not None:
                    completion_tokens = delta.completion_tokens

        try:
            async for event in pump(new_stream()):
                yield event
        except ProviderError as exc:
            # The model failed — expired key, exhausted quota, network blip. The
            # documents are still here, so fall back to answering from them
            # rather than returning an error page. Only safe before any token has
            # been sent; mid-stream, restarting would splice two answers together.
            if parts or not included:
                raise
            log.warning("chat.provider_failed_falling_back", detail=exc.detail)
            degraded = exc.detail
            answer_mode = "documents_only"
            model_label = None
            async for event in pump(new_stream(MockProvider(settings))):
                yield event

        query_duration.labels(stage="generate").observe(time.perf_counter() - stage)

        resolved = gen.resolve_citations("".join(parts), included)
        latency_ms = int((time.perf_counter() - started) * 1000)

        if resolved.unresolved_markers:
            unresolved_citations.inc(len(resolved.unresolved_markers))
            log.warning(
                "chat.unresolved_citations",
                markers=resolved.unresolved_markers,
                supplied=len(included),
            )
        citations_per_answer.observe(len(resolved.citations))
        if gen.is_no_answer(resolved.text):
            no_answer_total.inc()
        # Label token spend with the model that actually ran, so the metric stays
        # meaningful when a user switches keys mid-session.
        model = model_label or "offline"
        if prompt_tokens:
            tokens_total.labels(type="prompt", model=model).inc(prompt_tokens)
        if completion_tokens:
            tokens_total.labels(type="completion", model=model).inc(completion_tokens)

        message_id = await _persist_answer(
            sessionmaker,
            conversation_id,
            resolved,
            prompt_tokens,
            completion_tokens,
            latency_ms,
        )

        yield _sse(
            "citations",
            {"citations": [c.model_dump(mode="json") for c in resolved.citations]},
        )
        yield _sse(
            "done",
            {
                "message_id": str(message_id),
                "conversation_id": str(conversation_id),
                "latency_ms": latency_ms,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "answer_mode": answer_mode,
                "model": model_label,
                # Present only when the model was meant to answer and could not;
                # the answer above came from the documents instead.
                "degraded_reason": degraded,
            },
        )
        query_duration.labels(stage="total").observe(time.perf_counter() - started)

        log.info(
            "chat.answered",
            conversation_id=str(conversation_id),
            # The question is logged; document content never is. In this vertical
            # the documents are client-confidential by definition.
            question=request.question,
            answer_mode=answer_mode,
            chunk_ids=[str(c.id) for c in included],
            scores=[round(c.score, 4) for c in included],
            citations=len(resolved.citations),
            latency_ms=latency_ms,
        )

    except asyncio.CancelledError:  # pragma: no cover - client aborted
        raise
    except AppError as exc:
        log.warning("chat.failed", reason=exc.problem_type, detail=exc.detail)
        yield _sse(
            "error", {"type": exc.problem_type, "title": exc.title, "detail": exc.detail}
        )
    except Exception:
        log.exception("chat.unhandled")
        yield _sse(
            "error",
            {
                "type": "/errors/internal",
                "title": "Internal server error",
                # Once the stream has started the status code is already 200, so
                # errors must be delivered in-band.
                "detail": "The answer could not be generated. Please try again.",
            },
        )


def _source_payload(chunk: RetrievedChunk, marker: int) -> dict[str, object]:
    return Citation(
        marker=marker,
        chunk_id=chunk.id,
        document_id=chunk.document_id,
        filename=chunk.filename,
        page=chunk.page_start,
        section_path=chunk.section_path,
        bbox=[dict(box) for box in chunk.bbox],
        snippet=chunk.content[:320],
        score=round(chunk.score, 4),
    ).model_dump(mode="json")


async def _emit_no_sources(
    sessionmaker: object,
    conversation_id: uuid.UUID,
    started: float,
    answer_mode: str,
) -> AsyncIterator[str]:
    """No chunk cleared retrieval — answer honestly instead of inventing one."""
    no_answer_total.inc()
    text = gen.NO_ANSWER_TEXT
    latency_ms = int((time.perf_counter() - started) * 1000)
    resolved = gen.ResolvedAnswer(text=text, citations=[], unresolved_markers=[])
    message_id = await _persist_answer(
        sessionmaker, conversation_id, resolved, None, None, latency_ms
    )
    yield _sse("sources", {"sources": []})
    yield _sse("token", {"text": text})
    yield _sse("citations", {"citations": []})
    yield _sse(
        "done",
        {
            "message_id": str(message_id),
            "conversation_id": str(conversation_id),
            "latency_ms": latency_ms,
            "prompt_tokens": None,
            "completion_tokens": None,
            "answer_mode": answer_mode,
            "model": None,
            "degraded_reason": None,
        },
    )


async def _persist_answer(
    sessionmaker: object,
    conversation_id: uuid.UUID,
    resolved: gen.ResolvedAnswer,
    prompt_tokens: int | None,
    completion_tokens: int | None,
    latency_ms: int,
) -> uuid.UUID:
    async with sessionmaker() as session:  # type: ignore[operator]
        message = Message(
            conversation_id=conversation_id,
            role="assistant",
            content=resolved.text,
            citations=[c.model_dump(mode="json") for c in resolved.citations],
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            latency_ms=latency_ms,
        )
        session.add(message)
        await session.commit()
        return message.id


async def _get_or_create_conversation(
    session: AsyncSession, conversation_id: uuid.UUID | None, question: str
) -> Conversation:
    if conversation_id is not None:
        conversation = await session.get(Conversation, conversation_id)
        if conversation is None:
            raise NotFoundError(f"No conversation with id {conversation_id}.")
        return conversation
    title = question.strip()
    conversation = Conversation(title=title[:80] + ("…" if len(title) > 80 else ""))
    session.add(conversation)
    await session.flush()
    return conversation


async def _load_history(
    session: AsyncSession, conversation_id: uuid.UUID, limit: int
) -> list[tuple[str, str]]:
    if limit <= 0:
        return []
    result = await session.execute(
        select(Message.role, Message.content)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.desc())
        .limit(limit)
    )
    return [(role, content) for role, content in reversed(result.all())]


@router.get("/conversations", response_model=list[ConversationSummary])
async def list_conversations(
    session: AsyncSession = Depends(get_session),
) -> list[ConversationSummary]:
    result = await session.execute(
        select(Conversation, func.count(Message.id))
        .outerjoin(Message, Message.conversation_id == Conversation.id)
        .group_by(Conversation.id)
        .order_by(Conversation.created_at.desc())
        .limit(100)
    )
    return [
        ConversationSummary(
            id=conversation.id,
            title=conversation.title,
            created_at=conversation.created_at,
            message_count=count,
        )
        for conversation, count in result.all()
    ]


@router.get("/conversations/{conversation_id}", response_model=ConversationOut)
async def get_conversation(
    conversation_id: uuid.UUID, session: AsyncSession = Depends(get_session)
) -> ConversationOut:
    conversation = await session.get(Conversation, conversation_id)
    if conversation is None:
        raise NotFoundError(f"No conversation with id {conversation_id}.")
    result = await session.execute(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at)
    )
    messages = [
        MessageOut(
            id=m.id,
            role=m.role,
            content=m.content,
            citations=[Citation.model_validate(c) for c in (m.citations or [])],
            prompt_tokens=m.prompt_tokens,
            completion_tokens=m.completion_tokens,
            latency_ms=m.latency_ms,
            created_at=m.created_at,
        )
        for m in result.scalars()
    ]
    return ConversationOut(
        id=conversation.id,
        title=conversation.title,
        created_at=conversation.created_at,
        messages=messages,
    )
