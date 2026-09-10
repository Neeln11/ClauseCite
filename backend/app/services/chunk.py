"""Structure-aware chunking.

Naive fixed-size chunking is the single biggest cause of bad RAG answers: it
splits a clause down the middle so that neither half answers the question. This
module splits on document structure first and falls back to token counting only
when a single paragraph exceeds the hard ceiling.

Three decisions carry most of the quality:

1. **Headings become a `section_path`** ("3. Termination > 3.2 Notice Period"),
   which is prepended to the *embedded* text but not the *stored* text. A lease
   clause reading "...ninety (90) days written notice" is ambiguous without its
   heading; with it, the embedding lands much closer to "termination notice".
2. **Numbered clauses are hard split candidates.** In contracts, `3.2` / `(a)` /
   `(iv)` are the real semantic boundaries, and respecting them is worth more
   than any amount of embedding-model shopping.
3. **Overlap does not cross a heading.** Carrying the tail of section 3.1 into
   section 3.2 makes 3.2 retrievable for questions it cannot answer.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field

from app.services.extract import ExtractedDocument, Line
from app.services.tokens import count_tokens

# 3. / 3.2 / 3.2.1 / (a) / (iv) / ARTICLE IV / Section 12 / Clause 4
_CLAUSE_RE = re.compile(
    r"""^\s*(
        \d+\.[\d.]*                       # 3.  3.2  3.2.1
      | \(\s*[a-zA-Z]{1,3}\s*\)           # (a) (iv) (A)
      | \[\s*\d+\s*\]                     # [1]
      | (?:ARTICLE|SECTION|CLAUSE|SCHEDULE|EXHIBIT|APPENDIX|ANNEX)\b[\s:.]*
        [\dIVXLCivxlc]*
    )""",
    re.VERBOSE,
)

_NUMBER_PREFIX_RE = re.compile(r"^\s*(\d+(?:\.\d+)*)\.?\s+")
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.;:!?])\s+(?=[A-Z(\"'“])")

_MAX_HEADING_CHARS = 120
_HEADING_SIZE_RATIO = 1.12
# Below this, a chunk is too small to stand alone as a retrieval result, so a
# structural boundary is ignored rather than emitting a two-line fragment.
_MIN_CHUNK_TOKEN_RATIO = 0.25
# JSONB guard: a pathological page can produce thousands of line rectangles and
# nobody needs 2000 highlights to see where an answer came from.
_MAX_BBOX_RECTS = 240


@dataclass(slots=True)
class ChunkDraft:
    chunk_index: int
    content: str
    embed_text: str
    token_count: int
    page_start: int
    page_end: int
    bbox: list[dict[str, float | int]]
    section_path: str | None
    id: uuid.UUID = field(default_factory=uuid.uuid4)


@dataclass(slots=True)
class _Heading:
    level: int
    text: str


def is_clause_start(text: str) -> bool:
    """True when a line opens a numbered or lettered clause."""
    return bool(_CLAUSE_RE.match(text))


def _heading_level(text: str, size: float, body_size: float) -> int | None:
    """Return a nesting level for a heading line, or None if it is body text."""
    stripped = text.strip()
    if not stripped or len(stripped) > _MAX_HEADING_CHARS:
        return None

    # Numbered heading: nesting comes straight from the numbering depth, which is
    # more reliable than font size in documents typeset without a style sheet.
    number_match = _NUMBER_PREFIX_RE.match(stripped)
    remainder = stripped[number_match.end() :] if number_match else stripped

    # A line ending in a full stop is almost always a sentence, not a heading --
    # unless it is a bare number-and-title with no other punctuation.
    looks_like_sentence = stripped.endswith(".") and len(remainder.split()) > 8

    letters = [c for c in remainder if c.isalpha()]
    all_caps = bool(letters) and all(c.isupper() for c in letters)
    big = size >= body_size * _HEADING_SIZE_RATIO if body_size else False

    if number_match and not looks_like_sentence and (big or all_caps or len(remainder) < 60):
        return len(number_match.group(1).split("."))
    if all_caps and not looks_like_sentence and len(stripped) > 2:
        return 1
    if big and not looks_like_sentence:
        return 1
    return None


def _merge_same_line_boxes(lines: list[Line]) -> list[dict[str, float | int]]:
    """One rectangle per visual line, grouped by page.

    Per-span rectangles look like a ransom note in the viewer, so spans were
    already unioned into lines during extraction. Here, lines whose vertical
    extents overlap substantially are merged too: a heading split across two
    text blocks is one visual line to the reader and should be one highlight.
    """
    by_page: dict[int, list[list[float]]] = {}
    for line in lines:
        x0, y0, x1, y1 = line.bbox
        rects = by_page.setdefault(line.page, [])
        for rect in rects:
            overlap = min(rect[3], y1) - max(rect[1], y0)
            height = min(rect[3] - rect[1], y1 - y0)
            if height > 0 and overlap > height * 0.6:
                rect[0] = min(rect[0], x0)
                rect[1] = min(rect[1], y0)
                rect[2] = max(rect[2], x1)
                rect[3] = max(rect[3], y1)
                break
        else:
            rects.append([x0, y0, x1, y1])

    out: list[dict[str, float | int]] = []
    for page in sorted(by_page):
        # Top-to-bottom in reading order; PDF space has y increasing upward.
        for rect in sorted(by_page[page], key=lambda r: -r[3]):
            out.append(
                {
                    "page": page,
                    "x0": round(rect[0], 2),
                    "y0": round(rect[1], 2),
                    "x1": round(rect[2], 2),
                    "y1": round(rect[3], 2),
                }
            )
    return out[:_MAX_BBOX_RECTS]


def _split_oversized_line(line: Line, max_tokens: int) -> list[Line]:
    """Split a single over-long line, preferring sentence boundaries.

    The bbox of every fragment is the whole original line: sub-line coordinates
    would require re-walking spans, and a highlight that covers slightly more
    than the quoted sentence is a far better failure than no highlight.
    """
    if count_tokens(line.text) <= max_tokens:
        return [line]

    pieces = [p for p in _SENTENCE_SPLIT_RE.split(line.text) if p.strip()]
    if len(pieces) == 1:
        words = line.text.split()
        chunk_size = max(1, len(words) // (count_tokens(line.text) // max_tokens + 1))
        pieces = [" ".join(words[i : i + chunk_size]) for i in range(0, len(words), chunk_size)]

    out: list[Line] = []
    buffer: list[str] = []
    for piece in pieces:
        candidate = " ".join([*buffer, piece])
        if buffer and count_tokens(candidate) > max_tokens:
            out.append(_clone_line(line, " ".join(buffer)))
            buffer = [piece]
        else:
            buffer.append(piece)
    if buffer:
        out.append(_clone_line(line, " ".join(buffer)))
    return out


def _clone_line(line: Line, text: str) -> Line:
    return Line(text=text, page=line.page, bbox=line.bbox, size=line.size, bold=line.bold)


def chunk_document(
    document: ExtractedDocument,
    *,
    target_tokens: int = 600,
    max_tokens: int = 900,
    overlap_tokens: int = 100,
) -> list[ChunkDraft]:
    body_size = document.body_size
    min_chunk_tokens = int(target_tokens * _MIN_CHUNK_TOKEN_RATIO)

    section_stack: list[_Heading] = []
    drafts: list[ChunkDraft] = []
    buffer: list[Line] = []
    buffer_tokens = 0
    buffer_section: str | None = None

    def current_section() -> str | None:
        return " > ".join(h.text for h in section_stack) or None

    def flush() -> list[Line]:
        """Emit the buffer as a chunk and return it (for overlap carry-over)."""
        nonlocal buffer, buffer_tokens, buffer_section
        emitted = buffer
        if emitted:
            drafts.append(_build_draft(len(drafts), emitted, buffer_section))
        buffer = []
        buffer_tokens = 0
        buffer_section = None
        return emitted

    for line in _iter_lines(document):
        level = _heading_level(line.text, line.size, body_size)
        hard_boundary = level is not None or is_clause_start(line.text)

        # A structural boundary flushes the buffer, but only once the buffer is
        # substantial -- otherwise a page of "(a) ... (b) ... (c) ..." becomes
        # dozens of unretrievable fragments.
        if hard_boundary and buffer_tokens >= min_chunk_tokens:
            flush()  # deliberately no overlap carry-over across structure

        if level is not None:
            while section_stack and section_stack[-1].level >= level:
                section_stack.pop()
            section_stack.append(_Heading(level=level, text=line.text.strip()))

        for part in _split_oversized_line(line, max_tokens):
            part_tokens = count_tokens(part.text)

            if buffer and buffer_tokens + part_tokens > target_tokens:
                emitted = flush()
                carry = _overlap_lines(emitted, overlap_tokens)
                buffer = list(carry)
                buffer_tokens = sum(count_tokens(c.text) for c in carry)

            if buffer_section is None:
                buffer_section = current_section()
            buffer.append(part)
            buffer_tokens += part_tokens

            if buffer_tokens >= max_tokens:
                flush()

    flush()
    return [d for d in drafts if d.content.strip()]


def _iter_lines(document: ExtractedDocument) -> list[Line]:
    return [line for page in document.pages for line in page.lines]


def _overlap_lines(lines: list[Line], overlap_tokens: int) -> list[Line]:
    """Trailing lines of the previous chunk, up to the overlap budget."""
    if overlap_tokens <= 0:
        return []
    carry: list[Line] = []
    total = 0
    for line in reversed(lines):
        tokens = count_tokens(line.text)
        if total + tokens > overlap_tokens and carry:
            break
        carry.insert(0, line)
        total += tokens
    # Never carry the entire previous chunk; that would duplicate it wholesale.
    if len(carry) == len(lines) and len(lines) > 1:
        carry = carry[1:]
    return carry


def _build_draft(index: int, lines: list[Line], section_path: str | None) -> ChunkDraft:
    content = "\n".join(line.text for line in lines).strip()
    pages = [line.page for line in lines]
    # Section path goes into the embedded text only. Storing it in `content`
    # would leak the heading into quoted answers.
    embed_text = f"{section_path}\n\n{content}" if section_path else content
    return ChunkDraft(
        chunk_index=index,
        content=content,
        embed_text=embed_text,
        token_count=count_tokens(content),
        page_start=min(pages),
        page_end=max(pages),
        bbox=_merge_same_line_boxes(lines),
        section_path=section_path,
    )
