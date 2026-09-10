/**
 * Integration test: the real component tree against a mocked API.
 *
 * This is the test that would have caught a broken wiring between the SSE
 * client, the chat hook, and the citation chips — each of which is unit tested
 * in isolation and none of which proves the three work together.
 *
 * The viewer itself is not exercised here: it is lazily loaded and renders a PDF
 * through pdf.js, which needs a real canvas. Its logic lives in lib/highlight.ts
 * precisely so it can be tested without one.
 */

import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import App from './App'
import type { DocumentSummary } from './types'

const documents: DocumentSummary[] = [
  {
    id: 'doc-lease',
    filename: 'Henderson_Commercial_Lease.pdf',
    status: 'ready',
    page_count: 5,
    byte_size: 11_264,
    error_message: null,
    created_at: '2025-01-02T10:00:00Z',
    processed_at: '2025-01-02T10:00:04Z',
  },
  {
    id: 'doc-msa',
    filename: 'Brightline_Master_Services_Agreement.pdf',
    status: 'ready',
    page_count: 5,
    byte_size: 11_500,
    error_message: null,
    created_at: '2025-01-02T10:01:00Z',
    processed_at: '2025-01-02T10:01:05Z',
  },
  {
    id: 'doc-nda',
    filename: 'Mutual_NDA_Vantage_Whitcombe.pdf',
    status: 'processing',
    page_count: null,
    byte_size: 8_100,
    error_message: null,
    created_at: '2025-01-02T10:02:00Z',
    processed_at: null,
  },
]

const CITATION = {
  marker: 1,
  chunk_id: 'chunk-abc',
  document_id: 'doc-lease',
  filename: 'Henderson_Commercial_Lease.pdf',
  page: 2,
  section_path: 'ARTICLE 3 - TERMINATION > 3.2 Notice Period',
  bbox: [{ page: 2, x0: 80, y0: 190, x1: 515, y1: 205 }],
  snippet: 'Either party may terminate this agreement upon ninety (90) days prior written notice',
  score: 0.83,
}

/** An SSE body in the exact event order backend/app/api/chat.py emits. */
function chatStream(): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder()
  const frames = [
    ': open\n\n',
    `event: sources\ndata: ${JSON.stringify({ sources: [CITATION] })}\n\n`,
    `event: token\ndata: ${JSON.stringify({ text: 'Either party may terminate on ' })}\n\n`,
    `event: token\ndata: ${JSON.stringify({ text: 'ninety (90) days written notice [1].' })}\n\n`,
    `event: citations\ndata: ${JSON.stringify({ citations: [CITATION] })}\n\n`,
    `event: done\ndata: ${JSON.stringify({
      message_id: 'msg-1',
      conversation_id: 'conv-1',
      latency_ms: 1840,
      prompt_tokens: 612,
      completion_tokens: 48,
    })}\n\n`,
  ]
  return new ReadableStream({
    start(controller) {
      for (const frame of frames) controller.enqueue(encoder.encode(frame))
      controller.close()
    },
  })
}

let chatBodies: string[] = []

beforeEach(() => {
  chatBodies = []
  vi.stubGlobal(
    'fetch',
    vi.fn((input: string | URL | Request, init?: RequestInit) => {
      const url = typeof input === 'string' ? input : input.toString()

      if (url.endsWith('/api/documents')) {
        return Promise.resolve(
          new Response(JSON.stringify(documents), {
            status: 200,
            headers: { 'Content-Type': 'application/json' },
          }),
        )
      }
      if (url.endsWith('/api/chat')) {
        chatBodies.push(String(init?.body ?? ''))
        return Promise.resolve(
          new Response(chatStream(), {
            status: 200,
            headers: { 'Content-Type': 'text/event-stream' },
          }),
        )
      }
      return Promise.reject(new Error(`unexpected request: ${url}`))
    }),
  )
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('App', () => {
  it('lists documents with their indexing status', async () => {
    render(<App />)

    expect(await screen.findByText('Henderson_Commercial_Lease.pdf')).toBeInTheDocument()
    expect(screen.getByText('Mutual_NDA_Vantage_Whitcombe.pdf')).toBeInTheDocument()
    // Only the two ready documents count towards the search scope; the third is
    // still indexing and so cannot be searched.
    expect(screen.getByText('All 2 documents')).toBeInTheDocument()
    expect(screen.getByText('Searching all 2 documents')).toBeInTheDocument()
    expect(screen.getByText('Indexing')).toBeInTheDocument()
  })

  it('streams an answer and renders its citation as a clickable chip', async () => {
    render(<App />)
    await screen.findByText('Henderson_Commercial_Lease.pdf')

    const box = screen.getByLabelText('Your question')
    await userEvent.type(box, 'What is the notice period for termination?')
    await userEvent.click(screen.getByRole('button', { name: 'Ask' }))

    await waitFor(() =>
      expect(screen.getByText(/ninety \(90\) days written notice/)).toBeInTheDocument(),
    )

    // The chip resolves to the passage, and the answer's footer reports the
    // measured latency the `done` event carried.
    expect(await screen.findByRole('button', { name: /Source 1/ })).toBeInTheDocument()
    await waitFor(() => expect(screen.getByText(/1\.8s/)).toBeInTheDocument())
  })

  it('searches every document by default, and only the selection once narrowed', async () => {
    render(<App />)
    await screen.findByText('Henderson_Commercial_Lease.pdf')

    // Default: no explicit scope, which the API reads as "every ready document".
    const box = screen.getByLabelText('Your question')
    await userEvent.type(box, 'first question')
    await userEvent.click(screen.getByRole('button', { name: 'Ask' }))
    await waitFor(() => expect(chatBodies).toHaveLength(1))
    expect(JSON.parse(chatBodies[0]!).document_ids).toBeNull()

    // Unticking one leaves the other as the explicit scope.
    await userEvent.click(
      screen.getByLabelText('Include Henderson_Commercial_Lease.pdf in searches'),
    )
    await waitFor(() => expect(screen.getByText('1 of 2 selected')).toBeInTheDocument())

    await userEvent.type(screen.getByLabelText('Your question'), 'second question')
    await userEvent.click(screen.getByRole('button', { name: 'Ask' }))
    await waitFor(() => expect(chatBodies).toHaveLength(2))
    expect(JSON.parse(chatBodies[1]!).document_ids).toEqual(['doc-msa'])
  })

  it('carries the conversation id into follow-up questions', async () => {
    render(<App />)
    await screen.findByText('Henderson_Commercial_Lease.pdf')

    await userEvent.type(screen.getByLabelText('Your question'), 'first')
    await userEvent.click(screen.getByRole('button', { name: 'Ask' }))
    await waitFor(() => expect(chatBodies).toHaveLength(1))
    expect(JSON.parse(chatBodies[0]!).conversation_id).toBeNull()

    await userEvent.type(screen.getByLabelText('Your question'), 'and the break right?')
    await userEvent.click(screen.getByRole('button', { name: 'Ask' }))
    await waitFor(() => expect(chatBodies).toHaveLength(2))
    // Follow-ups must land in the same conversation or history is lost.
    expect(JSON.parse(chatBodies[1]!).conversation_id).toBe('conv-1')
  })

  it('offers suggested questions before the first turn and asks one on click', async () => {
    render(<App />)
    await screen.findByText('Henderson_Commercial_Lease.pdf')

    await userEvent.click(
      screen.getByRole('button', { name: 'What is the notice period for termination?' }),
    )
    await waitFor(() => expect(chatBodies).toHaveLength(1))
    expect(JSON.parse(chatBodies[0]!).question).toBe('What is the notice period for termination?')
  })
})
