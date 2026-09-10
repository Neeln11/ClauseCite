/**
 * The API contract, mirrored from backend/app/schemas.py.
 *
 * Kept hand-written rather than generated: the surface is small, and a generated
 * client would still need these names spelled out somewhere for the components to
 * read well. If the surface grows, generate from /openapi.json instead.
 */

export type DocumentStatus = 'pending' | 'processing' | 'ready' | 'failed'

/** A rectangle in PDF user space: origin bottom-left, units are points. */
export interface BBox {
  page: number
  x0: number
  y0: number
  x1: number
  y1: number
}

export interface DocumentSummary {
  id: string
  filename: string
  status: DocumentStatus
  page_count: number | null
  byte_size: number | null
  error_message: string | null
  created_at: string
  processed_at: string | null
}

export interface DocumentDetail extends DocumentSummary {
  chunk_count: number
}

export interface UploadAccepted {
  id: string
  filename: string
  status: DocumentStatus
  duplicate_of: string | null
}

export interface Citation {
  marker: number
  chunk_id: string
  document_id: string
  filename: string
  page: number
  section_path: string | null
  bbox: BBox[]
  snippet: string
  score: number | null
}

/** RFC 7807 problem+json — the shape every API error takes. */
export interface ProblemDetail {
  type: string
  title: string
  status: number
  detail: string | null
}

/**
 * How an answer was produced.
 *
 * `documents_only` — every sentence was selected from the uploaded documents.
 * `documents_and_llm` — a model generated it from those documents, and may have
 * added general knowledge that it is required to label as such.
 */
export type AnswerMode = 'documents_only' | 'documents_and_llm'

export interface ChatDone {
  message_id: string
  conversation_id: string
  latency_ms: number
  prompt_tokens: number | null
  completion_tokens: number | null
  answer_mode: AnswerMode
  model: string | null
  /** Set when a connected model failed and the documents answered instead. */
  degraded_reason: string | null
}

export interface ChatStreamError {
  type: string
  title: string
  detail: string
}

export interface MessageOut {
  id: string
  role: 'user' | 'assistant'
  content: string
  citations: Citation[]
  prompt_tokens: number | null
  completion_tokens: number | null
  latency_ms: number | null
  created_at: string
}

/**
 * A message as the UI holds it.
 *
 * `sources` is every passage handed to the model and arrives before the first
 * token, so a `[2]` chip is clickable the moment it is typed. `citations`
 * arrives at the end and narrows that set to what the answer actually cited;
 * until then, chips resolve against `sources`.
 */
export interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  sources: Citation[]
  citations: Citation[]
  streaming: boolean
  latencyMs: number | null
  promptTokens: number | null
  completionTokens: number | null
  answerMode: AnswerMode | null
  model: string | null
  degradedReason: string | null
  error: ChatStreamError | null
}
