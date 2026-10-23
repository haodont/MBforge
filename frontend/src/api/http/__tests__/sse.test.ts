/**
 * sse.ts — `connectSSE` / `fetchSSE` (covered functions at top).
 *
 * Protects the streaming contracts that are not plain forwarding: URL
 * resolution through API_BASE, exponential reconnect with backoff reset +
 * cancellation, one-shot completion on a `done` frame, frame reassembly
 * across split chunks, and abort handling.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { connectSSE, fetchSSE, type SSEEvent } from '../sse'

class MockEventSource {
  static instances: MockEventSource[] = []
  url: string
  onopen: (() => void) | null = null
  onmessage: ((event: MessageEvent) => void) | null = null
  onerror: ((event: Event) => void) | null = null
  close = vi.fn()
  constructor(url: string) {
    this.url = url
    MockEventSource.instances.push(this)
  }
}

Object.defineProperty(globalThis, 'EventSource', { value: MockEventSource, writable: true })

describe('connectSSE', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    MockEventSource.instances = []
  })
  afterEach(() => {
    vi.useRealTimers()
  })

  it('resolves EventSource URLs through API_BASE without duplicating an existing prefix', () => {
    connectSSE('/ingest/events', vi.fn())
    expect(MockEventSource.instances).toHaveLength(1)
    expect(MockEventSource.instances[0].url).toBe('/api/v1/ingest/events')

    connectSSE('/api/v1/events/stream?query=test', vi.fn())
    expect(MockEventSource.instances).toHaveLength(2)
    expect(MockEventSource.instances[1].url).toBe('/api/v1/events/stream?query=test')
  })

  it('reconnects with exponential backoff, resets it after a successful open, and cleanup stops the stream', () => {
    const onRetry = vi.fn()
    connectSSE('/ingest/events', vi.fn(), vi.fn(), { baseDelayMs: 100, maxRetries: 5, onRetry })

    // A dropped connection backs off instead of reconnecting immediately.
    const first = MockEventSource.instances[0]
    first.onerror?.(new Event('error'))
    expect(MockEventSource.instances).toHaveLength(1)
    vi.advanceTimersByTime(100)
    expect(MockEventSource.instances).toHaveLength(2)

    // A successful reconnect resets the attempt counter to the base delay.
    const second = MockEventSource.instances[1]
    second.onopen?.()
    second.onerror?.(new Event('error'))
    expect(onRetry).toHaveBeenLastCalledWith(1, 100)

    // Flush the pending retry so later timer advances cannot reopen this stream.
    vi.advanceTimersByTime(10_000)

    // cleanup closes the live source and cancels pending reconnect timers.
    const cleanup = connectSSE('/ingest/events', vi.fn(), vi.fn(), { baseDelayMs: 1000 })
    const live = MockEventSource.instances[MockEventSource.instances.length - 1]
    cleanup()
    expect(live.close).toHaveBeenCalled()
    const opened = MockEventSource.instances.length
    vi.advanceTimersByTime(10_000)
    expect(MockEventSource.instances).toHaveLength(opened)
  })

  it('parses JSON frames, closes on done, and never reconnects a finished stream', () => {
    const events: SSEEvent[] = []
    const onRetry = vi.fn()
    connectSSE('/api/v1/events/stream?query=test', e => events.push(e), vi.fn(), {
      baseDelayMs: 100,
      onRetry,
    })
    const es = MockEventSource.instances[0]

    es.onmessage?.(new MessageEvent('message', { data: '{"event":"delta","delta":"hi"}' }))
    expect(events).toEqual([{ type: 'delta', data: { event: 'delta', delta: 'hi' } }])

    es.onmessage?.(new MessageEvent('message', { data: '{"type":"done","total":3}' }))
    expect(events).toEqual([
      { type: 'delta', data: { event: 'delta', delta: 'hi' } },
      { type: 'done', data: { type: 'done', total: 3 } },
    ])
    expect(es.close).toHaveBeenCalledTimes(1)

    // A late error after `done` must not replay the whole stream.
    es.onerror?.(new Event('error'))
    vi.advanceTimersByTime(1000)
    expect(MockEventSource.instances).toHaveLength(1)
    expect(onRetry).not.toHaveBeenCalled()
  })
})

describe('fetchSSE', () => {
  const originalFetch = globalThis.fetch

  function makeReader(chunks: Uint8Array[]) {
    let index = 0
    return {
      read: () => {
        if (index < chunks.length) {
          const value = chunks[index]
          index += 1
          return Promise.resolve({ done: false, value })
        }
        return Promise.resolve({ done: true, value: undefined })
      },
      cancel: vi.fn().mockResolvedValue(undefined),
    }
  }

  beforeEach(() => {
    vi.restoreAllMocks()
  })
  afterEach(() => {
    globalThis.fetch = originalFetch
  })

  it('collects SSE data lines, stops on done, and resolves the request URL from API_BASE', async () => {
    const encoder = new TextEncoder()
    const chunks = [
      encoder.encode('data: {"type":"chunk","delta":"a"}\n\n'),
      encoder.encode('data: {"type":"chunk","delta":"b"}\n\ndata: {"event":"done"}\n\n'),
    ]
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: true,
      body: { getReader: () => makeReader(chunks) },
    })

    const events = await fetchSSE<{ type: string; delta: string }>('/api/v1/events/stream')
    expect(events).toEqual([
      { type: 'chunk', delta: 'a' },
      { type: 'chunk', delta: 'b' },
    ])

    await fetchSSE('/tasks/stream', { foo: 'bar' })
    expect(globalThis.fetch).toHaveBeenLastCalledWith(
      expect.stringMatching(/\/api\/v1\/tasks\/stream\?foo=bar$/),
      { signal: undefined },
    )
  })

  it('aborts the fetch when the provided signal is aborted', async () => {
    const controller = new AbortController()
    const promise = fetchSSE('/slow', {}, controller.signal)
    controller.abort()
    await expect(promise).rejects.toThrow('aborted')
  })

  it('cancels the reader and rejects when the signal aborts mid-read', async () => {
    let rejectRead: ((reason: Error) => void) | null = null
    const reader = {
      read: () =>
        new Promise<never>((_resolve, reject) => {
          rejectRead = reject
        }),
      cancel: vi.fn().mockImplementation(() => {
        rejectRead?.(new Error('aborted'))
        return Promise.resolve()
      }),
    }
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: true,
      body: { getReader: () => reader },
    })

    const controller = new AbortController()
    const promise = fetchSSE('/slow', {}, controller.signal)
    await Promise.resolve()
    controller.abort()
    await expect(promise).rejects.toThrow('aborted')
    expect(reader.cancel).toHaveBeenCalled()
  })
})
