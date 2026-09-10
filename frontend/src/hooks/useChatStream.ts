/**
 * Chat state driven by the SSE stream.
 *
 * Token events arrive faster than anyone can read, so appending straight to state
 * would re-render on every word. Tokens are buffered and flushed on animation
 * frames instead: the text still appears to stream, but React renders at the
 * refresh rate rather than at the token rate.
 */

import { useCallback, useEffect, useRef, useState } from 'react'

import { ApiError, streamChat } from '../api/client'
import type { ChatDone, ChatMessage, ChatStreamError, Citation } from '../types'

let sequence = 0
const nextId = (prefix: string) => `${prefix}-${++sequence}`

export function useChatStream() {
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [conversationId, setConversationId] = useState<string | null>(null)
  const [streaming, setStreaming] = useState(false)

  const abortRef = useRef<AbortController | null>(null)
  const frameRef = useRef<number | null>(null)
  const pendingRef = useRef('')

  const cancelFrame = useCallback(() => {
    if (frameRef.current !== null) {
      cancelAnimationFrame(frameRef.current)
      frameRef.current = null
    }
  }, [])

  useEffect(
    () => () => {
      abortRef.current?.abort()
      cancelFrame()
    },
    [cancelFrame],
  )

  const patch = useCallback((id: string, changes: Partial<ChatMessage>) => {
    setMessages((current) =>
      current.map((message) => (message.id === id ? { ...message, ...changes } : message)),
    )
  }, [])

  const ask = useCallback(
    async (question: string, documentIds: string[] | null) => {
      const trimmed = question.trim()
      if (!trimmed || streaming) return

      const answerId = nextId('assistant')
      setMessages((current) => [
        ...current,
        {
          id: nextId('user'),
          role: 'user',
          content: trimmed,
          sources: [],
          citations: [],
          streaming: false,
          latencyMs: null,
          promptTokens: null,
          completionTokens: null,
          answerMode: null,
          model: null,
          degradedReason: null,
          error: null,
        },
        {
          id: answerId,
          role: 'assistant',
          content: '',
          sources: [],
          citations: [],
          streaming: true,
          latencyMs: null,
          promptTokens: null,
          completionTokens: null,
          answerMode: null,
          model: null,
          degradedReason: null,
          error: null,
        },
      ])
      setStreaming(true)

      const controller = new AbortController()
      abortRef.current = controller
      pendingRef.current = ''

      const flush = () => {
        frameRef.current = null
        const buffered = pendingRef.current
        if (!buffered) return
        pendingRef.current = ''
        setMessages((current) =>
          current.map((message) =>
            message.id === answerId
              ? { ...message, content: message.content + buffered }
              : message,
          ),
        )
      }

      const scheduleFlush = () => {
        if (frameRef.current === null) frameRef.current = requestAnimationFrame(flush)
      }

      try {
        await streamChat(
          {
            question: trimmed,
            conversationId,
            documentIds,
          },
          {
            onSources: (sources: Citation[]) => patch(answerId, { sources }),
            onToken: (text: string) => {
              pendingRef.current += text
              scheduleFlush()
            },
            onCitations: (citations: Citation[]) => {
              cancelFrame()
              flush()
              patch(answerId, { citations })
            },
            onDone: (done: ChatDone) => {
              cancelFrame()
              flush()
              setConversationId(done.conversation_id)
              patch(answerId, {
                streaming: false,
                latencyMs: done.latency_ms,
                promptTokens: done.prompt_tokens,
                completionTokens: done.completion_tokens,
                answerMode: done.answer_mode,
                model: done.model,
                degradedReason: done.degraded_reason,
              })
            },
            onError: (error: ChatStreamError) => {
              cancelFrame()
              flush()
              patch(answerId, { streaming: false, error })
            },
          },
          controller.signal,
        )
      } catch (caught) {
        cancelFrame()
        flush()
        patch(answerId, {
          streaming: false,
          error:
            caught instanceof ApiError
              ? { type: caught.type, title: caught.title, detail: caught.detail }
              : {
                  type: '/errors/unknown',
                  title: 'Something went wrong',
                  detail: 'The answer could not be generated. Please try again.',
                },
        })
      } finally {
        cancelFrame()
        flush()
        // A stream cut short by `stop()` still has to leave the bubble settled,
        // not spinning forever.
        setMessages((current) =>
          current.map((message) =>
            message.id === answerId && message.streaming
              ? { ...message, streaming: false }
              : message,
          ),
        )
        setStreaming(false)
        abortRef.current = null
      }
    },
    [cancelFrame, conversationId, patch, streaming],
  )

  const stop = useCallback(() => {
    abortRef.current?.abort()
  }, [])

  const reset = useCallback(() => {
    abortRef.current?.abort()
    cancelFrame()
    pendingRef.current = ''
    setMessages([])
    setConversationId(null)
    setStreaming(false)
  }, [cancelFrame])

  return { messages, conversationId, streaming, ask, stop, reset }
}
