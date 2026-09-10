"""Pydantic request/response models — the public API contract."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

DocumentStatus = Literal["pending", "processing", "ready", "failed"]

# How an answer was produced. `documents_only` means every sentence was selected
# from the uploaded documents; `documents_and_llm` means a model generated it
# from those same documents and may have added labelled general knowledge.
AnswerMode = Literal["documents_only", "documents_and_llm"]


class ProviderStatus(BaseModel):
    """The active answering mode, as reported to the UI."""

    mode: Literal["offline", "llm"]
    provider_id: str | None = None
    provider_name: str | None = None
    model: str | None = None
    message: str


class BBox(BaseModel):
    """A rectangle in PDF coordinate space (origin top-left, points)."""

    page: int
    x0: float
    y0: float
    x1: float
    y1: float


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    filename: str
    status: DocumentStatus
    page_count: int | None = None
    byte_size: int | None = None
    error_message: str | None = None
    created_at: datetime
    processed_at: datetime | None = None


class DocumentDetail(DocumentOut):
    chunk_count: int = 0


class UploadAccepted(BaseModel):
    id: uuid.UUID
    filename: str
    status: DocumentStatus
    duplicate_of: uuid.UUID | None = Field(
        default=None,
        description="Set when this file's sha256 matched an existing document; no re-ingest ran.",
    )


class Citation(BaseModel):
    marker: int
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    filename: str
    page: int
    section_path: str | None = None
    bbox: list[BBox] = Field(default_factory=list)
    snippet: str
    score: float | None = None


class ChatRequest(BaseModel):
    conversation_id: uuid.UUID | None = None
    question: str = Field(min_length=1, max_length=2000)
    document_ids: list[uuid.UUID] | None = Field(
        default=None, description="null searches every ready document"
    )


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    role: Literal["user", "assistant"]
    content: str
    citations: list[Citation] = Field(default_factory=list)
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    latency_ms: int | None = None
    created_at: datetime


class ConversationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str | None
    created_at: datetime
    messages: list[MessageOut] = Field(default_factory=list)


class ConversationSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str | None
    created_at: datetime
    message_count: int = 0


# ---- SSE event payloads (documented for the frontend, not returned directly) ----


class TokenEvent(BaseModel):
    text: str


class CitationsEvent(BaseModel):
    citations: list[Citation]


class DoneEvent(BaseModel):
    message_id: uuid.UUID
    conversation_id: uuid.UUID
    latency_ms: int
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    answer_mode: AnswerMode = "documents_only"
    model: str | None = Field(
        default=None, description="null in documents_only mode — no model ran"
    )
    degraded_reason: str | None = Field(
        default=None,
        description="Set when a connected model failed and the documents answered instead.",
    )


class ErrorEvent(BaseModel):
    type: str
    title: str
    detail: str


class ProblemDetail(BaseModel):
    """RFC 7807 problem+json."""

    type: str
    title: str
    status: int
    detail: str | None = None


class ReadyCheck(BaseModel):
    status: Literal["ready", "degraded"]
    checks: dict[str, str]
