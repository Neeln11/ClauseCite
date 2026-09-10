/**
 * Minimal Server-Sent Events parser.
 *
 * `EventSource` cannot be used here: it only issues GET requests, and asking a
 * question is a POST with a JSON body. So the stream is read from `fetch` and
 * framed by hand.
 *
 * The one thing worth being careful about is that network chunks have nothing to
 * do with event boundaries — a single `data:` line routinely arrives split
 * across two reads. Everything not yet terminated by a blank line stays in the
 * buffer until it is complete.
 */

export interface SSEEvent {
  event: string
  data: string
}

/** Split a raw SSE text buffer into complete events plus the unparsed remainder. */
export function parseEventBuffer(buffer: string): { events: SSEEvent[]; rest: string } {
  const normalised = buffer.replace(/\r\n/g, '\n')
  const blocks = normalised.split('\n\n')
  // The final block has not been terminated by a blank line yet, so it is
  // incomplete by definition and carries over to the next read.
  const rest = blocks.pop() ?? ''

  const events: SSEEvent[] = []
  for (const block of blocks) {
    let event = 'message'
    const data: string[] = []
    for (const line of block.split('\n')) {
      // ": open" and friends are comments used to flush headers early.
      if (line.startsWith(':') || line.trim() === '') continue
      const colon = line.indexOf(':')
      const field = colon === -1 ? line : line.slice(0, colon)
      const rawValue = colon === -1 ? '' : line.slice(colon + 1)
      const value = rawValue.startsWith(' ') ? rawValue.slice(1) : rawValue
      if (field === 'event') event = value
      else if (field === 'data') data.push(value)
    }
    if (data.length > 0) events.push({ event, data: data.join('\n') })
  }
  return { events, rest }
}

/** Read a `fetch` body to completion, yielding each SSE event in order. */
export async function* readEventStream(
  body: ReadableStream<Uint8Array>,
): AsyncGenerator<SSEEvent> {
  const reader = body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  try {
    for (;;) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      const { events, rest } = parseEventBuffer(buffer)
      buffer = rest
      for (const event of events) yield event
    }
    // A well-behaved server ends with a blank line, but flush anything left so a
    // final event is never dropped on an abrupt close.
    buffer += decoder.decode()
    const { events } = parseEventBuffer(buffer + '\n\n')
    for (const event of events) yield event
  } finally {
    reader.releaseLock()
  }
}
