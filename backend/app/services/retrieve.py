"""Retrieval: vector search, keyword search, and rank fusion.

Vector search alone fails on exactly what people ask a contract tool about —
party names, clause numbers, defined terms, dollar amounts. "What does clause
7.3(b) say?" is a lexical query wearing a semantic costume. So both searches run
and their rankings are fused.

Reciprocal Rank Fusion is the right default because it consumes *ranks*, not
scores: no normalisation, no weight to tune, and no risk that a cosine similarity
of 0.83 gets compared against a ts_rank of 0.04 as though they were commensurable.

Both searches have two implementations. On PostgreSQL they are index-backed SQL
(pgvector's `<=>` and a GIN-indexed tsvector). On SQLite — the zero-setup local
mode — there is no vector operator and no full-text ranking, so both are computed
in Python over the candidate rows. The fusion, the scores, and the returned shape
are identical either way; only the cost model differs, which is why production
keeps PostgreSQL.
"""

from __future__ import annotations

import math
import re
import uuid
from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import Select, and_, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import is_sqlite
from app.models import Chunk, Document

RRF_K = 60

_WORD_RE = re.compile(r"[a-z0-9']+")
_STOPWORDS = frozenset(
    """a an and any are as at be been by for from has have if in is it its of on or
    shall such that the their there these this to under upon was were which will with
    what when where who whom how does do did can could would should""".split()
)


@dataclass(slots=True)
class RetrievedChunk:
    id: uuid.UUID
    document_id: uuid.UUID
    filename: str
    chunk_index: int
    content: str
    token_count: int
    page_start: int
    page_end: int
    bbox: list[dict[str, Any]] = field(default_factory=list)
    section_path: str | None = None
    score: float = 0.0

    @property
    def label(self) -> str:
        section = f", §{self.section_path.split(' > ')[-1]}" if self.section_path else ""
        return f"{self.filename}, p.{self.page_start}{section}"


def _base_query(document_ids: Sequence[uuid.UUID] | None) -> Any:
    conditions = [Document.status == "ready"]
    if document_ids:
        conditions.append(Chunk.document_id.in_(list(document_ids)))
    return and_(*conditions)


def _row_to_chunk(chunk: Chunk, filename: str, score: float) -> RetrievedChunk:
    return RetrievedChunk(
        id=chunk.id,
        document_id=chunk.document_id,
        filename=filename,
        chunk_index=chunk.chunk_index,
        content=chunk.content,
        token_count=chunk.token_count,
        page_start=chunk.page_start,
        page_end=chunk.page_end,
        bbox=list(chunk.bbox or []),
        section_path=chunk.section_path,
        score=float(score),
    )


async def _candidate_rows(
    session: AsyncSession, document_ids: Sequence[uuid.UUID] | None
) -> list[tuple[Chunk, str]]:
    """Every indexed chunk, for the in-Python search paths."""
    stmt: Select[Any] = (
        select(Chunk, Document.filename)
        .join(Document, Document.id == Chunk.document_id)
        .where(_base_query(document_ids))
    )
    return [(row[0], row[1]) for row in (await session.execute(stmt)).all()]


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    dot = 0.0
    norm_a = 0.0
    norm_b = 0.0
    for x, y in zip(a, b, strict=False):
        dot += x * y
        norm_a += x * x
        norm_b += y * y
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / math.sqrt(norm_a * norm_b)


def _terms(text: str) -> list[str]:
    return [w for w in _WORD_RE.findall(text.lower()) if w not in _STOPWORDS]


async def vector_search(
    session: AsyncSession,
    embedding: list[float],
    *,
    document_ids: Sequence[uuid.UUID] | None = None,
    k: int = 12,
) -> list[RetrievedChunk]:
    if is_sqlite():
        scored = [
            (_cosine(embedding, chunk.embedding), chunk, filename)
            for chunk, filename in await _candidate_rows(session, document_ids)
        ]
        # Ties break on chunk id so repeated runs return the same order.
        scored.sort(key=lambda item: (-item[0], str(item[1].id)))
        return [_row_to_chunk(c, f, s) for s, c, f in scored[:k]]

    distance = Chunk.embedding.cosine_distance(embedding)
    stmt: Select[Any] = (
        select(Chunk, Document.filename, (1 - distance).label("score"))
        .join(Document, Document.id == Chunk.document_id)
        .where(_base_query(document_ids))
        .order_by(distance)
        .limit(k)
    )
    rows = (await session.execute(stmt)).all()
    return [_row_to_chunk(row[0], row[1], row[2]) for row in rows]


async def keyword_search(
    session: AsyncSession,
    question: str,
    *,
    document_ids: Sequence[uuid.UUID] | None = None,
    k: int = 12,
) -> list[RetrievedChunk]:
    if is_sqlite():
        query_terms = set(_terms(question))
        if not query_terms:
            return []
        scored: list[tuple[float, Chunk, str]] = []
        for chunk, filename in await _candidate_rows(session, document_ids):
            counts = Counter(_terms(chunk.content))
            if not counts:
                continue
            total = sum(counts.values())
            # Sub-linear term frequency, scaled by how much of the question the
            # chunk covers. Mirrors what ts_rank rewards: several distinct query
            # terms present beats one term repeated.
            weight = sum(1.0 + math.log(counts[t]) for t in query_terms if counts[t])
            if weight == 0.0:
                continue
            coverage = sum(1 for t in query_terms if counts[t]) / len(query_terms)
            scored.append((weight * coverage / math.sqrt(total), chunk, filename))
        scored.sort(key=lambda item: (-item[0], str(item[1].id)))
        return [_row_to_chunk(c, f, s) for s, c, f in scored[:k]]

    tsvector = func.to_tsvector("english", Chunk.content)
    # websearch_to_tsquery never raises on user input, unlike to_tsquery, which
    # syntax-errors on a stray quote and turns a question into a 500.
    tsquery = func.websearch_to_tsquery("english", question)
    rank = func.ts_rank(tsvector, tsquery)
    stmt: Select[Any] = (
        select(Chunk, Document.filename, rank.label("score"))
        .join(Document, Document.id == Chunk.document_id)
        .where(and_(_base_query(document_ids), tsvector.op("@@")(tsquery)))
        .order_by(desc(rank))
        .limit(k)
    )
    rows = (await session.execute(stmt)).all()
    return [_row_to_chunk(row[0], row[1], row[2]) for row in rows]


def reciprocal_rank_fusion(
    *rankings: Sequence[RetrievedChunk], k: int = RRF_K
) -> list[RetrievedChunk]:
    """Fuse ranked lists. Returns chunks ordered by fused score, deduplicated."""
    scores: dict[uuid.UUID, float] = defaultdict(float)
    chunks: dict[uuid.UUID, RetrievedChunk] = {}
    # Ties are broken by original rank in the first list that contained the chunk,
    # which keeps output order deterministic across runs.
    first_seen: dict[uuid.UUID, tuple[int, int]] = {}

    for list_index, ranking in enumerate(rankings):
        for rank, chunk in enumerate(ranking, start=1):
            scores[chunk.id] += 1 / (k + rank)
            if chunk.id not in chunks:
                chunks[chunk.id] = chunk
                first_seen[chunk.id] = (list_index, rank)

    ordered = sorted(scores.items(), key=lambda item: (-item[1], first_seen[item[0]]))
    result = []
    for chunk_id, score in ordered:
        chunk = chunks[chunk_id]
        chunk.score = score
        result.append(chunk)
    return result


async def retrieve(
    session: AsyncSession,
    *,
    question: str,
    embedding: list[float],
    document_ids: Sequence[uuid.UUID] | None = None,
    top_k: int | None = None,
    final_k: int | None = None,
    hybrid: bool | None = None,
) -> list[RetrievedChunk]:
    settings = get_settings()
    top_k = top_k or settings.retrieval_top_k
    final_k = final_k or settings.retrieval_final_k
    hybrid = settings.retrieval_hybrid if hybrid is None else hybrid

    vector_hits = await vector_search(
        session, embedding, document_ids=document_ids, k=top_k
    )
    if not hybrid:
        return vector_hits[:final_k]

    keyword_hits = await keyword_search(session, question, document_ids=document_ids, k=top_k)
    if not keyword_hits:
        return vector_hits[:final_k]
    return reciprocal_rank_fusion(vector_hits, keyword_hits)[:final_k]


def assemble_context(
    chunks: Sequence[RetrievedChunk], *, max_tokens: int | None = None
) -> tuple[str, list[RetrievedChunk]]:
    """Build the numbered SOURCES block.

    Ordered by document, then by position in that document — deliberately *not*
    by relevance. Models reason better over text in its natural reading order, and
    presenting §3.3 above §3.2 invites an answer that contradicts itself across
    two adjacent clauses.

    Returns the rendered block and the chunks that actually made it in, so that
    citation markers and sources can never drift out of sync.
    """
    max_tokens = max_tokens or get_settings().max_context_tokens
    ordered = sorted(chunks, key=lambda c: (c.filename, c.chunk_index))

    included: list[RetrievedChunk] = []
    blocks: list[str] = []
    total = 0
    for chunk in ordered:
        # +40 covers the header line and blank-line separator.
        cost = chunk.token_count + 40
        if included and total + cost > max_tokens:
            break
        marker = len(included) + 1
        section = f", §{chunk.section_path}" if chunk.section_path else ""
        pages = (
            f"p.{chunk.page_start}"
            if chunk.page_start == chunk.page_end
            else f"pp.{chunk.page_start}-{chunk.page_end}"
        )
        blocks.append(f"[{marker}] {chunk.filename}, {pages}{section}\n{chunk.content}")
        included.append(chunk)
        total += cost

    return "\n\n".join(blocks), included
