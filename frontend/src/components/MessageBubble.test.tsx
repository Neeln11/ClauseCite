import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import type { ChatMessage, Citation } from '../types'

import { MessageBubble } from './MessageBubble'

function citation(marker: number, overrides: Partial<Citation> = {}): Citation {
  return {
    marker,
    chunk_id: `chunk-${marker}`,
    document_id: 'doc-1',
    filename: 'Henderson_Commercial_Lease.pdf',
    page: 4,
    section_path: 'ARTICLE 3 - TERMINATION > 3.2 Notice Period',
    bbox: [{ page: 4, x0: 72, y0: 310, x1: 520, y1: 348 }],
    snippet: 'Either party may terminate this agreement upon ninety (90) days prior written notice',
    score: 0.82,
    ...overrides,
  }
}

function message(overrides: Partial<ChatMessage> = {}): ChatMessage {
  return {
    id: 'assistant-1',
    role: 'assistant',
    content: 'The notice period is ninety (90) days [1].',
    sources: [citation(1)],
    citations: [citation(1)],
    streaming: false,
    latencyMs: 1840,
    promptTokens: 512,
    completionTokens: 100,
    answerMode: 'documents_only',
    model: null,
    degradedReason: null,
    error: null,
    ...overrides,
  }
}

describe('MessageBubble', () => {
  it('renders a citation marker as a clickable chip and passes the citation up', async () => {
    const onSelect = vi.fn()
    render(
      <MessageBubble message={message()} activeChunkId={null} onSelectCitation={onSelect} />,
    )

    const chip = screen.getByRole('button', { name: /Source 1/ })
    await userEvent.click(chip)

    expect(onSelect).toHaveBeenCalledTimes(1)
    expect(onSelect.mock.calls[0]?.[0]).toMatchObject({ chunk_id: 'chunk-1', page: 4 })
  })

  it('names the source and page in the chip label so it works from a screen reader', () => {
    render(<MessageBubble message={message()} activeChunkId={null} onSelectCitation={vi.fn()} />)
    expect(
      screen.getByRole('button', {
        name: /Henderson_Commercial_Lease\.pdf, p\.4, 3\.2 Notice Period/,
      }),
    ).toBeInTheDocument()
  })

  it('marks the chip active when its passage is the one open in the viewer', () => {
    render(
      <MessageBubble message={message()} activeChunkId="chunk-1" onSelectCitation={vi.fn()} />,
    )
    expect(screen.getByRole('button', { name: /Source 1/ })).toHaveClass('chip-active')
  })

  it('resolves chips against the sources event while the answer is still streaming', () => {
    // `citations` has not arrived yet, but `[1]` must already be clickable.
    render(
      <MessageBubble
        message={message({ citations: [], streaming: true, latencyMs: null })}
        activeChunkId={null}
        onSelectCitation={vi.fn()}
      />,
    )
    expect(screen.getByRole('button', { name: /Source 1/ })).toBeInTheDocument()
  })

  it('leaves a hallucinated marker as plain text', () => {
    render(
      <MessageBubble
        message={message({ content: 'Ninety days [7].', citations: [citation(1)] })}
        activeChunkId={null}
        onSelectCitation={vi.fn()}
      />,
    )
    expect(screen.queryByRole('button', { name: /Source 7/ })).not.toBeInTheDocument()
    expect(screen.getByText(/Ninety days \[7\]\./)).toBeInTheDocument()
  })

  it('shows latency, tokens, and citation count once the answer settles', () => {
    render(<MessageBubble message={message()} activeChunkId={null} onSelectCitation={vi.fn()} />)
    expect(screen.getByText(/1\.8s · 100 tokens · 1 citation/)).toBeInTheDocument()
  })

  it('surfaces an in-band stream error', () => {
    render(
      <MessageBubble
        message={message({
          error: { type: '/errors/internal', title: 'Internal server error', detail: 'Try again.' },
        })}
        activeChunkId={null}
        onSelectCitation={vi.fn()}
      />,
    )
    expect(screen.getByRole('alert')).toHaveTextContent('Internal server error. Try again.')
  })

  it('labels an offline answer as coming only from the documents', () => {
    render(<MessageBubble message={message()} activeChunkId={null} onSelectCitation={vi.fn()} />)
    expect(screen.getByTitle(/taken from your uploaded documents/i)).toHaveTextContent(
      'Documents only',
    )
  })

  it('labels a generated answer and names the model that produced it', () => {
    render(
      <MessageBubble
        message={message({ answerMode: 'documents_and_llm', model: 'claude-opus-5' })}
        activeChunkId={null}
        onSelectCitation={vi.fn()}
      />,
    )
    const badge = screen.getByText('Documents + AI')
    expect(badge).toBeInTheDocument()
    expect(badge).toHaveAttribute('title', expect.stringContaining('claude-opus-5'))
  })

  it('explains a downgrade when the connected model could not be reached', () => {
    render(
      <MessageBubble
        message={message({ degradedReason: 'The API key was rejected.' })}
        activeChunkId={null}
        onSelectCitation={vi.fn()}
      />,
    )
    expect(screen.getByText(/Answered from your documents only/)).toBeInTheDocument()
    expect(screen.getByText(/The API key was rejected\./)).toBeInTheDocument()
    // A downgrade is a caveat on a good answer, not an error.
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('omits the mode badge while the answer is still streaming', () => {
    render(
      <MessageBubble
        message={message({ streaming: true, answerMode: null, latencyMs: null })}
        activeChunkId={null}
        onSelectCitation={vi.fn()}
      />,
    )
    expect(screen.queryByText(/Documents only|Documents \+ AI/)).not.toBeInTheDocument()
  })

  it('renders a user turn as plain text with no citation affordances', () => {
    render(
      <MessageBubble
        message={message({ role: 'user', content: 'What is the notice period?', citations: [] })}
        activeChunkId={null}
        onSelectCitation={vi.fn()}
      />,
    )
    expect(screen.getByText('What is the notice period?')).toBeInTheDocument()
    expect(screen.queryByRole('button')).not.toBeInTheDocument()
  })
})
