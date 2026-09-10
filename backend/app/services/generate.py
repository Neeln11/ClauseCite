"""Prompt assembly, citation resolution, and answer streaming."""

from __future__ import annotations

import re
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass

from app.schemas import BBox, Citation
from app.services.provider import AIProvider, ChatDelta, get_provider
from app.services.retrieve import RetrievedChunk

SYSTEM_PROMPT = """\
You answer questions using ONLY the numbered sources provided below.

Rules:
- Every factual claim must carry a citation marker in the form [1], [2].
- If a claim draws on several sources, cite them all: [1][3].
- If the sources do not contain the answer, say so plainly:
  "The documents provided don't cover this." Do not speculate or use
  outside knowledge.
- If sources conflict, surface the conflict and cite both.
- Quote exact language when the precise wording matters (dates, amounts,
  obligations, deadlines). Paraphrase otherwise.
- Be concise. Answer the question asked; do not summarise the document.

SOURCES:
{numbered_sources}"""

# Used when a real LLM provider is active: the model may supplement document
# answers with its general knowledge, but must still prioritise the sources.
SYSTEM_PROMPT_LLM = """\
You are an expert assistant. Answer the question using the numbered source documents
provided below as your primary reference. You may also draw on your general knowledge
to fill in context the documents don't cover, but you MUST:

- Cite every claim that comes from a source document with [n] markers (e.g. [1], [2]).
- Clearly label any information from your general knowledge that is NOT in the
  documents with a note such as: (general knowledge — not in the uploaded documents).
- If sources conflict with each other or with your knowledge, surface the conflict.
- Quote exact language for dates, amounts, obligations, and deadlines.
- Be concise. Answer the question asked; do not summarise the document.

SOURCES:
{numbered_sources}"""

# Used when an LLM is connected but retrieval matched nothing. Answering from
# general knowledge is the useful behaviour here — but it has to be unmistakable
# that no document backed it, or the product's one promise is broken.
SYSTEM_PROMPT_NO_SOURCES = """\
No uploaded document matched this question, so you have no sources to cite.

Answer from your general knowledge, and begin your reply with exactly this line:

No matching content was found in your documents. Answering from general knowledge:

Then answer. Be concise. Do not invent citations or [n] markers — there are no
sources to point at. If you are unsure, say so."""

NO_ANSWER_TEXT = "The documents provided don't cover this."

# Matches [1], [12], and the comma form some models emit despite instructions: [1, 3]
_MARKER_RE = re.compile(r"\[(\d+(?:\s*,\s*\d+)*)\]")
_SNIPPET_CHARS = 320


@dataclass(slots=True)
class ResolvedAnswer:
    text: str
    citations: list[Citation]
    unresolved_markers: list[int]


def build_system_prompt(numbered_sources: str, *, llm_mode: bool = False) -> str:
    template = SYSTEM_PROMPT_LLM if llm_mode else SYSTEM_PROMPT
    return template.format(numbered_sources=numbered_sources)



def build_messages(
    question: str, history: Sequence[tuple[str, str]], *, limit: int = 4
) -> list[dict[str, str]]:
    """Recent turns plus the new question.

    Only the last `limit` messages are included: enough for "and what about
    termination?" to resolve its referent, cheap enough that nobody needs to think
    about it, and short enough that stale context cannot drown the new question.
    """
    recent = list(history)[-limit:] if limit > 0 else []
    messages = [{"role": role, "content": content} for role, content in recent]
    messages.append({"role": "user", "content": question})
    return messages


def _snippet(content: str) -> str:
    flat = " ".join(content.split())
    if len(flat) <= _SNIPPET_CHARS:
        return flat
    cut = flat[:_SNIPPET_CHARS]
    space = cut.rfind(" ")
    return (cut[:space] if space > _SNIPPET_CHARS * 0.6 else cut).rstrip(" ,;:") + "…"


def resolve_citations(
    text: str, sources: Sequence[RetrievedChunk]
) -> ResolvedAnswer:
    """Map `[n]` markers onto the sources they were numbered from.

    Models occasionally cite `[7]` when six sources were supplied. Such markers are
    stripped from the answer rather than rendered: a citation chip the user cannot
    click is worse than no chip at all, because it breaks the one promise this
    product makes. The count is returned so it can be recorded as a metric —
    unresolved markers are the cheapest hallucination signal available.
    """
    by_marker = dict(enumerate(sources, start=1))
    used: dict[int, RetrievedChunk] = {}
    unresolved: list[int] = []

    def replace(match: re.Match[str]) -> str:
        markers = [int(part) for part in match.group(1).split(",")]
        kept: list[int] = []
        for marker in markers:
            chunk = by_marker.get(marker)
            if chunk is None:
                unresolved.append(marker)
                continue
            used.setdefault(marker, chunk)
            kept.append(marker)
        return "".join(f"[{m}]" for m in kept)

    cleaned = _MARKER_RE.sub(replace, text)
    # Stripping a marker can leave " ." or a double space behind.
    cleaned = re.sub(r"\s+([.,;:])", r"\1", cleaned)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned).strip()

    citations = [
        Citation(
            marker=marker,
            chunk_id=chunk.id,
            document_id=chunk.document_id,
            filename=chunk.filename,
            page=chunk.page_start,
            section_path=chunk.section_path,
            bbox=[BBox(**box) for box in chunk.bbox],
            snippet=_snippet(chunk.content),
            score=round(chunk.score, 4),
        )
        for marker, chunk in sorted(used.items())
    ]
    return ResolvedAnswer(text=cleaned, citations=citations, unresolved_markers=unresolved)


def llm_is_active(provider: AIProvider | None = None) -> bool:
    """Whether a user-supplied model will generate the next answer.

    Defined as "not the offline provider" rather than by listing the LLM classes,
    so adding a provider does not require remembering to update this check.
    """
    from app.services.provider import MockProvider

    return not isinstance(provider or get_provider(), MockProvider)


async def stream_answer(
    *,
    question: str,
    history: Sequence[tuple[str, str]],
    numbered_sources: str,
    history_limit: int = 4,
    provider: AIProvider | None = None,
) -> AsyncIterator[ChatDelta]:

    provider = provider or get_provider()
    # With an LLM connected the model may supplement the sources with its own
    # knowledge, provided it labels it. Offline, the answer is strictly extractive.
    system = build_system_prompt(numbered_sources, llm_mode=llm_is_active(provider))
    messages = build_messages(question, history, limit=history_limit)
    async for delta in provider.stream_chat(system, messages):
        yield delta


async def stream_without_sources(
    *,
    question: str,
    history: Sequence[tuple[str, str]],
    history_limit: int = 4,
    provider: AIProvider | None = None,
) -> AsyncIterator[ChatDelta]:
    """Answer when retrieval found nothing and an LLM is connected."""

    provider = provider or get_provider()
    messages = build_messages(question, history, limit=history_limit)
    async for delta in provider.stream_chat(SYSTEM_PROMPT_NO_SOURCES, messages):
        yield delta


def is_no_answer(text: str) -> bool:
    """Whether the model declined to answer — tracked as a quality metric."""
    normalised = " ".join(text.lower().split())
    return "don't cover this" in normalised or "do not cover this" in normalised
