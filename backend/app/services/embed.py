"""Embedding with batching.

Batches are bounded by *both* item count and token count. The item limit alone is
not enough: 96 chunks of 900 tokens exceeds the per-request token ceiling and the
resulting 400 looks like a mysterious intermittent failure at exactly the moment
you are ingesting your most interesting document.
"""

from __future__ import annotations

from collections.abc import Sequence

from app.config import get_settings
from app.services.provider import AIProvider, get_provider
from app.services.tokens import count_tokens


def build_batches(
    texts: Sequence[str], *, max_items: int, max_tokens: int
) -> list[list[int]]:
    """Group text indexes into batches respecting both ceilings."""
    batches: list[list[int]] = []
    current: list[int] = []
    current_tokens = 0
    for index, text in enumerate(texts):
        tokens = count_tokens(text)
        too_many_items = len(current) >= max_items
        too_many_tokens = current and current_tokens + tokens > max_tokens
        if too_many_items or too_many_tokens:
            batches.append(current)
            current, current_tokens = [], 0
        current.append(index)
        current_tokens += tokens
    if current:
        batches.append(current)
    return batches


async def embed_texts(
    texts: Sequence[str], *, provider: AIProvider | None = None
) -> list[list[float]]:
    """Embed in provider-order-preserving batches."""
    if not texts:
        return []
    settings = get_settings()
    provider = provider or get_provider()

    vectors: list[list[float] | None] = [None] * len(texts)
    batches = build_batches(
        texts,
        max_items=settings.embedding_batch_size,
        max_tokens=settings.embedding_batch_max_tokens,
    )
    for batch in batches:
        result = await provider.embed([texts[i] for i in batch])
        for position, index in enumerate(batch):
            vectors[index] = result[position]

    missing = [i for i, v in enumerate(vectors) if v is None]
    if missing:
        raise RuntimeError(f"Provider returned no embedding for indexes {missing}")
    return [v for v in vectors if v is not None]


async def embed_query(question: str, *, provider: AIProvider | None = None) -> list[float]:
    vectors = await embed_texts([question], provider=provider)
    return vectors[0]
