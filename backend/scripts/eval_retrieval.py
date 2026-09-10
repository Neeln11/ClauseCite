"""Retrieval evaluation: recall@K against the hand-labelled set in eval_qa.json.

    python scripts/seed.py            # ingest the sample corpus first
    python scripts/eval_retrieval.py  # then measure retrieval quality

Unit tests catch a broken pipeline; they cannot catch a ranking regression
where retrieval still returns *something* plausible-looking but the actually
relevant document has slipped out of the top-K. This script is the coarse,
end-to-end proxy for that: it asks each question through the real /api/chat
path and checks whether a source from the expected document made the cut,
exactly as a user would judge "did it find the right contract."

It is deliberately not a pytest test — recall depends on the seeded corpus
being present and unmodified, which is a fixture cost pytest's suite avoids by
mocking everything. Run it by hand, or wire it into CI as a separate,
non-blocking job once the corpus is judged stable enough to gate on.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

import httpx

DEFAULT_API = "http://127.0.0.1:8000"
QA_FILE = Path(__file__).resolve().parent / "eval_qa.json"


def _parse_sse(body: str) -> list[tuple[str, Any]]:
    events: list[tuple[str, Any]] = []
    for block in body.split("\n\n"):
        name: str | None = None
        payload: str | None = None
        for line in block.splitlines():
            if line.startswith("event: "):
                name = line[len("event: ") :]
            elif line.startswith("data: "):
                payload = line[len("data: ") :]
        if name is not None:
            events.append((name, json.loads(payload) if payload else None))
    return events


async def _ask(client: httpx.AsyncClient, question: str) -> list[str]:
    """Return the cited filenames, most-relevant first, deduplicated."""
    response = await client.post("/api/chat", json={"question": question})
    response.raise_for_status()
    events = _parse_sse(response.text)
    seen: list[str] = []
    for name, data in events:
        if name != "citations":
            continue
        for citation in data["citations"]:
            filename = citation["filename"]
            if filename not in seen:
                seen.append(filename)
    return seen


async def _run(api: str, top_k: int) -> int:
    pairs = json.loads(QA_FILE.read_text())["pairs"]
    hits = 0
    async with httpx.AsyncClient(base_url=api, timeout=60.0) as client:
        for pair in pairs:
            question = pair["question"]
            expected = set(pair["expected_filenames"])
            cited = await _ask(client, question)
            hit = bool(expected & set(cited[:top_k]))
            hits += hit
            mark = "OK  " if hit else "MISS"
            print(f"[{mark}] {question}")
            if not hit:
                print(f"       expected one of: {sorted(expected)}")
                print(f"       got (top {top_k}): {cited[:top_k]}")

    recall = hits / len(pairs) if pairs else 0.0
    print(f"\nrecall@{top_k}: {hits}/{len(pairs)} = {recall:.0%}")
    return 0 if recall == 1.0 else 1


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api", default=DEFAULT_API)
    parser.add_argument("--top-k", type=int, default=5)
    args = parser.parse_args()
    sys.exit(asyncio.run(_run(args.api, args.top_k)))


if __name__ == "__main__":
    main()
