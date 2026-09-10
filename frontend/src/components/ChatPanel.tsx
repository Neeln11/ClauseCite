/**
 * The conversation: transcript, composer, and the empty state.
 *
 * Auto-scroll follows the stream, but only while the user is already at the
 * bottom. Yanking the view back down while someone is reading an earlier answer
 * is the single most irritating thing a chat UI can do.
 */

import { useEffect, useRef, useState } from 'react'

import type { ChatMessage, Citation } from '../types'

import { MessageBubble } from './MessageBubble'

const SUGGESTIONS = [
  'What is the notice period for termination?',
  'What is the cap on liability, and what falls outside it?',
  'How much is the monthly rent, and when is it reviewed?',
  'How long do the confidentiality obligations last?',
]

interface Props {
  messages: ChatMessage[]
  streaming: boolean
  scopeLabel: string
  hasReadyDocuments: boolean
  activeChunkId: string | null
  onAsk: (question: string) => void
  onStop: () => void
  onReset: () => void
  onSelectCitation: (citation: Citation) => void
}

export function ChatPanel({
  messages,
  streaming,
  scopeLabel,
  hasReadyDocuments,
  activeChunkId,
  onAsk,
  onStop,
  onReset,
  onSelectCitation,
}: Props) {
  const [draft, setDraft] = useState('')
  const scrollRef = useRef<HTMLDivElement | null>(null)
  const pinnedRef = useRef(true)

  // Track whether the user is at the bottom; only then does the view follow.
  const handleScroll = () => {
    const element = scrollRef.current
    if (!element) return
    const distance = element.scrollHeight - element.scrollTop - element.clientHeight
    pinnedRef.current = distance < 80
  }

  useEffect(() => {
    if (!pinnedRef.current) return
    const element = scrollRef.current
    if (element) element.scrollTop = element.scrollHeight
  }, [messages])

  const submit = (question: string) => {
    const trimmed = question.trim()
    if (!trimmed || streaming) return
    pinnedRef.current = true
    onAsk(trimmed)
    setDraft('')
  }

  return (
    <section className="chat" aria-label="Conversation">
      <div className="chat-scroll" ref={scrollRef} onScroll={handleScroll}>
        {messages.length === 0 ? (
          <div className="chat-empty">
            <h2>Ask across your contracts</h2>
            <p>
              Answers are drawn only from the documents you have uploaded, and every claim carries a
              citation you can click through to the exact passage in the source PDF.
            </p>
            {hasReadyDocuments ? (
              <ul className="suggestions">
                {SUGGESTIONS.map((suggestion) => (
                  <li key={suggestion}>
                    <button type="button" onClick={() => submit(suggestion)}>
                      {suggestion}
                    </button>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="chat-empty-note">
                Upload a contract to get started. Nothing can be answered until at least one
                document has finished indexing.
              </p>
            )}
          </div>
        ) : (
          <div className="chat-turns">
            {messages.map((message) => (
              <MessageBubble
                key={message.id}
                message={message}
                activeChunkId={activeChunkId}
                onSelectCitation={onSelectCitation}
              />
            ))}
          </div>
        )}
      </div>

      <form
        className="composer"
        onSubmit={(event) => {
          event.preventDefault()
          submit(draft)
        }}
      >
        <div className="composer-row">
          <textarea
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={(event) => {
              // Enter sends; Shift+Enter is a newline. Matches every chat UI a
              // user has already learned.
              if (event.key === 'Enter' && !event.shiftKey) {
                event.preventDefault()
                submit(draft)
              }
            }}
            placeholder={
              hasReadyDocuments
                ? 'Ask a question about these contracts…'
                : 'Upload a document first…'
            }
            rows={1}
            maxLength={2000}
            disabled={!hasReadyDocuments}
            aria-label="Your question"
          />
          {streaming ? (
            <button type="button" className="button button-secondary" onClick={onStop}>
              Stop
            </button>
          ) : (
            <button
              type="submit"
              className="button"
              disabled={!draft.trim() || !hasReadyDocuments}
            >
              Ask
            </button>
          )}
        </div>
        <div className="composer-foot">
          <span>{scopeLabel}</span>
          {messages.length > 0 && (
            <button type="button" className="text-button" onClick={onReset} disabled={streaming}>
              New conversation
            </button>
          )}
        </div>
      </form>
    </section>
  )
}
