/**
 * Typed API client.
 *
 * Two things it deliberately centralises:
 *
 * 1. **Error shape.** Every backend error is RFC 7807 problem+json, so every
 *    failure here becomes an `ApiError` carrying the human-readable `title` and
 *    `detail`. Components can render `error.detail` without special-casing.
 * 2. **SSE.** Asking a question is a POST, which rules out `EventSource`, so the
 *    stream is read from the `fetch` body and dispatched to typed callbacks.
 */

import { readEventStream } from '../lib/sse'
import type {
  ChatDone,
  ChatStreamError,
  Citation,
  DocumentDetail,
  DocumentSummary,
  MessageOut,
  ProblemDetail,
  UploadAccepted,
} from '../types'

// 127.0.0.1 rather than localhost: uvicorn binds 127.0.0.1 by default, and on
// Windows "localhost" can resolve to ::1 first — which nothing is listening on.
// Override with VITE_API_URL when the API lives elsewhere.
export const API_URL: string = (
  import.meta.env.VITE_API_URL ?? 'http://127.0.0.1:8000'
).replace(/\/$/, '')

export class ApiError extends Error {
  readonly status: number
  readonly title: string
  readonly detail: string
  readonly type: string

  constructor(problem: ProblemDetail) {
    super(problem.detail || problem.title)
    this.name = 'ApiError'
    this.status = problem.status
    this.title = problem.title
    this.detail = problem.detail || problem.title
    this.type = problem.type
  }
}

async function toApiError(response: Response): Promise<ApiError> {
  try {
    const problem = (await response.json()) as Partial<ProblemDetail>
    return new ApiError({
      type: problem.type ?? '/errors/unknown',
      title: problem.title ?? response.statusText,
      status: problem.status ?? response.status,
      detail: problem.detail ?? null,
    })
  } catch {
    // A proxy returning HTML, or an empty body. Still surface something useful.
    return new ApiError({
      type: '/errors/unknown',
      title: response.statusText || 'Request failed',
      status: response.status,
      detail: `The server returned ${response.status}.`,
    })
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response
  try {
    response = await fetch(`${API_URL}${path}`, init)
  } catch {
    // fetch only rejects on transport failure, which in practice means the
    // backend is not running — by far the most common local-dev error.
    throw new ApiError({
      type: '/errors/unreachable',
      title: 'Cannot reach the API',
      status: 0,
      detail: `No response from ${API_URL}. Is the backend running?`,
    })
  }
  if (!response.ok) throw await toApiError(response)
  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}

// ---- Documents -------------------------------------------------------------

export function listDocuments(): Promise<DocumentSummary[]> {
  return request<DocumentSummary[]>('/api/documents')
}

export function getDocument(id: string): Promise<DocumentDetail> {
  return request<DocumentDetail>(`/api/documents/${id}`)
}

export function deleteDocument(id: string): Promise<void> {
  return request<void>(`/api/documents/${id}`, { method: 'DELETE' })
}

export function documentFileUrl(id: string): string {
  return `${API_URL}/api/documents/${id}/file`
}

/**
 * Upload a PDF.
 *
 * XHR rather than fetch purely for `onProgress`: a 25 MB contract on a slow
 * connection needs a progress bar, and fetch cannot report upload progress.
 */
export function uploadDocument(
  file: File,
  onProgress?: (fraction: number) => void,
): Promise<UploadAccepted> {
  return new Promise((resolve, reject) => {
    const form = new FormData()
    form.append('file', file, file.name)

    const xhr = new XMLHttpRequest()
    xhr.open('POST', `${API_URL}/api/documents`)
    xhr.responseType = 'text'

    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable && onProgress) onProgress(event.loaded / event.total)
    }

    xhr.onload = () => {
      let parsed: unknown = null
      try {
        parsed = JSON.parse(xhr.responseText)
      } catch {
        parsed = null
      }
      if (xhr.status >= 200 && xhr.status < 300) {
        onProgress?.(1)
        resolve(parsed as UploadAccepted)
        return
      }
      const problem = (parsed ?? {}) as Partial<ProblemDetail>
      reject(
        new ApiError({
          type: problem.type ?? '/errors/upload-failed',
          title: problem.title ?? 'Upload failed',
          status: problem.status ?? xhr.status,
          detail: problem.detail ?? `The server returned ${xhr.status}.`,
        }),
      )
    }

    xhr.onerror = () =>
      reject(
        new ApiError({
          type: '/errors/unreachable',
          title: 'Cannot reach the API',
          status: 0,
          detail: `No response from ${API_URL}. Is the backend running?`,
        }),
      )

    xhr.send(form)
  })
}

// ---- Conversations ---------------------------------------------------------

export function getConversation(id: string): Promise<{
  id: string
  title: string | null
  created_at: string
  messages: MessageOut[]
}> {
  return request(`/api/conversations/${id}`)
}

// ---- Chat ------------------------------------------------------------------

export interface ChatStreamHandlers {
  onSources?: (sources: Citation[]) => void
  onToken?: (text: string) => void
  onCitations?: (citations: Citation[]) => void
  onDone?: (done: ChatDone) => void
  onError?: (error: ChatStreamError) => void
}

export interface ChatStreamRequest {
  question: string
  conversationId?: string | null
  documentIds?: string[] | null
}

/**
 * Ask a question and dispatch the SSE events as they arrive.
 *
 * Errors raised after the stream has started cannot change the status code — it
 * is already 200 — so the backend delivers them in band as an `error` event.
 * Both paths funnel into `onError` so callers have one thing to handle.
 */
export async function streamChat(
  { question, conversationId, documentIds }: ChatStreamRequest,
  handlers: ChatStreamHandlers,
  signal?: AbortSignal,
): Promise<void> {
  let response: Response
  try {
    response = await fetch(`${API_URL}/api/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
      body: JSON.stringify({
        question,
        conversation_id: conversationId ?? null,
        document_ids: documentIds && documentIds.length > 0 ? documentIds : null,
      }),
      signal,
    })
  } catch {
    if (signal?.aborted) return
    throw new ApiError({
      type: '/errors/unreachable',
      title: 'Cannot reach the API',
      status: 0,
      detail: `No response from ${API_URL}. Is the backend running?`,
    })
  }

  if (!response.ok) throw await toApiError(response)
  if (!response.body) {
    throw new ApiError({
      type: '/errors/no-stream',
      title: 'Empty response',
      status: response.status,
      detail: 'The server accepted the question but returned no stream.',
    })
  }

  for await (const event of readEventStream(response.body)) {
    if (signal?.aborted) return
    switch (event.event) {
      case 'sources':
        handlers.onSources?.(parse<{ sources: Citation[] }>(event.data)?.sources ?? [])
        break
      case 'token':
        handlers.onToken?.(parse<{ text: string }>(event.data)?.text ?? '')
        break
      case 'citations':
        handlers.onCitations?.(parse<{ citations: Citation[] }>(event.data)?.citations ?? [])
        break
      case 'done': {
        const done = parse<ChatDone>(event.data)
        if (done) handlers.onDone?.(done)
        break
      }
      case 'error': {
        const problem = parse<ChatStreamError>(event.data)
        handlers.onError?.(
          problem ?? {
            type: '/errors/internal',
            title: 'Stream error',
            detail: 'The answer could not be generated.',
          },
        )
        break
      }
      default:
        break
    }
  }
}

function parse<T>(data: string): T | null {
  try {
    return JSON.parse(data) as T
  } catch {
    return null
  }
}

// ---- Provider Settings -----------------------------------------------------

export interface ProviderStatus {
  mode: 'offline' | 'llm'
  provider_id: string | null
  provider_name: string | null
  model: string | null
  message: string
}

export interface ProviderOption {
  provider_id: string
  provider_name: string
}

/**
 * The key is normally the only required input: the backend detects provider,
 * endpoint, and model from it. The rest let the UI override that guess —
 * `provider_id` skips detection for a known provider, and "custom" plus
 * `base_url`/`model` targets any OpenAI-compatible endpoint the backend has
 * no detection rule for.
 */
export interface ProviderConfigRequest {
  api_key: string
  provider_id?: string
  base_url?: string
  model?: string
}

export function getProviderStatus(): Promise<ProviderStatus> {
  return request<ProviderStatus>('/api/provider/status')
}

export function getProviderOptions(): Promise<ProviderOption[]> {
  return request<ProviderOption[]>('/api/provider/options')
}

export function configureProvider(config: ProviderConfigRequest): Promise<ProviderStatus> {
  return request<ProviderStatus>('/api/provider/configure', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(config),
  })
}

export function clearProvider(): Promise<ProviderStatus> {
  return request<ProviderStatus>('/api/provider/configure', { method: 'DELETE' })
}
