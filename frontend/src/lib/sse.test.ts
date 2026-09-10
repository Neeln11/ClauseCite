import { describe, expect, it } from 'vitest'

import { parseEventBuffer, readEventStream } from './sse'

describe('parseEventBuffer', () => {
  it('parses complete events and returns the incomplete tail', () => {
    const { events, rest } = parseEventBuffer(
      'event: token\ndata: {"text":"hello"}\n\nevent: token\ndata: {"text":"wor',
    )
    expect(events).toEqual([{ event: 'token', data: '{"text":"hello"}' }])
    expect(rest).toBe('event: token\ndata: {"text":"wor')
  })

  it('ignores comment lines used to flush headers', () => {
    const { events } = parseEventBuffer(': open\n\nevent: done\ndata: {}\n\n')
    expect(events).toEqual([{ event: 'done', data: '{}' }])
  })

  it('joins multi-line data fields with a newline', () => {
    const { events } = parseEventBuffer('event: token\ndata: first\ndata: second\n\n')
    expect(events[0]?.data).toBe('first\nsecond')
  })

  it('handles CRLF line endings and a missing space after the colon', () => {
    const { events } = parseEventBuffer('event:token\r\ndata:{"text":"x"}\r\n\r\n')
    expect(events).toEqual([{ event: 'token', data: '{"text":"x"}' }])
  })

  it('defaults the event name to message when only data is sent', () => {
    const { events } = parseEventBuffer('data: bare\n\n')
    expect(events[0]?.event).toBe('message')
  })
})

describe('readEventStream', () => {
  /** A stream whose chunk boundaries deliberately fall mid-event. */
  function streamOf(chunks: string[]): ReadableStream<Uint8Array> {
    const encoder = new TextEncoder()
    return new ReadableStream({
      start(controller) {
        for (const chunk of chunks) controller.enqueue(encoder.encode(chunk))
        controller.close()
      },
    })
  }

  it('reassembles events split across network chunks', async () => {
    const stream = streamOf([
      ': open\n\nevent: sou',
      'rces\ndata: {"sources":[]}\n\nevent: token\ndata: {"te',
      'xt":"ninety days"}\n\n',
      'event: done\ndata: {"latency_ms":42}\n\n',
    ])

    const seen: string[] = []
    for await (const event of readEventStream(stream)) {
      seen.push(`${event.event}:${event.data}`)
    }

    expect(seen).toEqual([
      'sources:{"sources":[]}',
      'token:{"text":"ninety days"}',
      'done:{"latency_ms":42}',
    ])
  })

  it('flushes a final event that was not terminated by a blank line', async () => {
    const seen: string[] = []
    for await (const event of readEventStream(streamOf(['event: done\ndata: {"ok":true}']))) {
      seen.push(event.event)
    }
    expect(seen).toEqual(['done'])
  })

  it('decodes multi-byte characters split across chunk boundaries', async () => {
    const encoder = new TextEncoder()
    const full = encoder.encode('event: token\ndata: {"text":"90 days — notice"}\n\n')
    // Cut inside the three-byte em dash.
    const split = full.indexOf(0xe2) + 1
    const stream = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(full.slice(0, split))
        controller.enqueue(full.slice(split))
        controller.close()
      },
    })

    const events = []
    for await (const event of readEventStream(stream)) events.push(event)
    expect(JSON.parse(events[0]!.data)).toEqual({ text: '90 days — notice' })
  })
})
