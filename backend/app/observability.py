"""Structured logging and Prometheus metrics.

The metrics that matter here are not the latency histograms — every service has
those. They are `rag_unresolved_citations_total`, `rag_no_answer_total`, and
`rag_retrieval_top_score`: signals about *answer quality*, not system health. A
retrieval regression shows up as top scores drifting down and no-answers drifting
up long before anyone files a bug saying "it feels worse".
"""

from __future__ import annotations

import logging
import sys
import uuid
from collections.abc import MutableMapping
from contextvars import ContextVar
from typing import Any

import structlog
from prometheus_client import Counter, Histogram

request_id_var: ContextVar[str] = ContextVar("request_id", default="-")

# ---- Metrics --------------------------------------------------------------

ingest_duration = Histogram(
    "rag_ingest_duration_seconds",
    "Wall-clock time to ingest one document",
    labelnames=("status",),
    buckets=(1, 2.5, 5, 10, 20, 40, 80, 160, 320),
)

# NOTE: the design doc labels this by document_id. Deliberately not done: an
# unbounded label creates one time series per uploaded file and will eventually
# take down the scrape. Per-document counts live in the structured logs, where
# high cardinality is free.
ingest_chunks = Histogram(
    "rag_ingest_chunks",
    "Chunks produced per document",
    buckets=(1, 5, 10, 25, 50, 100, 250, 500, 1000),
)

ingest_documents = Counter(
    "rag_ingest_documents_total", "Documents ingested", labelnames=("status",)
)

query_duration = Histogram(
    "rag_query_duration_seconds",
    "Per-stage query latency",
    labelnames=("stage",),  # embed | retrieve | generate | total
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2, 4, 8, 16),
)

retrieval_top_score = Histogram(
    "rag_retrieval_top_score",
    "Fused score of the best-ranked chunk",
    buckets=(0.0, 0.005, 0.01, 0.015, 0.02, 0.025, 0.03, 0.05),
)

tokens_total = Counter(
    "rag_tokens_total", "Tokens consumed", labelnames=("type", "model")
)

citations_per_answer = Histogram(
    "rag_citations_per_answer",
    "Resolved citations per answer",
    buckets=(0, 1, 2, 3, 4, 5, 6, 8, 10),
)

unresolved_citations = Counter(
    "rag_unresolved_citations_total",
    "Citation markers referring to sources that were never supplied "
    "(hallucination signal)",
)

no_answer_total = Counter(
    "rag_no_answer_total", "Answers where the model reported no coverage"
)


# ---- Logging --------------------------------------------------------------


def _add_request_id(
    _logger: Any, _name: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    event_dict["request_id"] = request_id_var.get()
    return event_dict


def configure_logging(level: str = "INFO", *, json_output: bool = True) -> None:
    logging.basicConfig(
        format="%(message)s", stream=sys.stdout, level=getattr(logging, level.upper(), 20)
    )
    for noisy in ("uvicorn.access", "azure.core.pipeline.policies.http_logging_policy"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            _add_request_id,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer()
            if json_output
            else structlog.dev.ConsoleRenderer(colors=False),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, level.upper(), 20)
        ),
        cache_logger_on_first_use=True,
    )


def new_request_id() -> str:
    return uuid.uuid4().hex[:16]


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)
