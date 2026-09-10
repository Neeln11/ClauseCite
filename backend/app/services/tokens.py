"""Token counting.

tiktoken's `cl100k_base` is the encoding used by text-embedding-3-* and the
gpt-4o family's predecessors; for the purposes of *budgeting* (chunk sizes,
context caps) the small differences between modern encodings do not matter, and
using one encoding everywhere keeps chunk sizes stable if the chat model changes.

A character-ratio fallback exists so that token counting never becomes the reason
a container fails to start in an environment without the tiktoken data files.
"""

from __future__ import annotations

import functools

_FALLBACK_CHARS_PER_TOKEN = 4


@functools.lru_cache(maxsize=1)
def _encoder() -> object | None:
    try:
        import tiktoken

        return tiktoken.get_encoding("cl100k_base")
    except Exception:  # pragma: no cover - offline/missing-data environments
        return None


def count_tokens(text: str) -> int:
    if not text:
        return 0
    enc = _encoder()
    if enc is None:  # pragma: no cover
        return max(1, len(text) // _FALLBACK_CHARS_PER_TOKEN)
    return len(enc.encode(text, disallowed_special=()))  # type: ignore[attr-defined]


def truncate_to_tokens(text: str, limit: int) -> str:
    """Hard-truncate text to `limit` tokens. Used only as a last-resort guard."""
    if limit <= 0:
        return ""
    enc = _encoder()
    if enc is None:  # pragma: no cover
        return text[: limit * _FALLBACK_CHARS_PER_TOKEN]
    tokens = enc.encode(text, disallowed_special=())  # type: ignore[attr-defined]
    if len(tokens) <= limit:
        return text
    return enc.decode(tokens[:limit])  # type: ignore[attr-defined]
