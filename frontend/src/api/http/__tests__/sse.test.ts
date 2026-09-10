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

  it('connects to a relative API path using API_BASE', () => {
    connectSSE('/ingest/events', vi.fn())
    expect(MockEventSource.instances).toHaveLength(1)
    expect(MockEventSource.instances[0].url).toBe('/api/v1/ingest/events')
  })

  it('does not duplicate an API prefix already present in the path', () => {
    connectSSE('/api/v1/events/stream?query=test', vi.fn())
    expect(MockEventSource.instances).toHaveLength(1)
    expect(MockEventSource.instances[0].url).toBe('/api/v1/events/stream?query=test')
  })

  it('resets the reconnect backoff after a successful connection', () => {
    const onRetry = vi.fn()
    connectSSE('/ingest/events', vi.fn(), vi.fn(), { baseDelayMs: 100, maxRetries: 5, onRetry })

    const es = MockEventSource.instances[0]
    // First error schedules a 100ms retry (attempt 0 -> delay 100).
    es.onerror?.(new Event('error'))
    expect(MockEventSource.instances).toHaveLength(1)

    // Advance to the reconnect; the second EventSource is created.
    vi.advanceTimersByTime(100)
    expect(MockEventSource.instances).toHaveLength(2)

    // Simulate successful reconnect: backoff resets to 0.
    MockEventSource.instances[1].onopen?.()

    // The next error should again use the base delay, not 200ms.
    MockEventSource.instances[1].onerror?.(new Event('error'))
    expect(onRetry).toHaveBeenLastCalledWith(1, 100)
  })

  it('cleanup closes the EventSource and cancels pending reconnect timers', () => {
    const cleanup = connectSSE('/ingest/events', vi.fn(), vi.fn(), { baseDelayMs: 1000 })
    const es = MockEventSource.instances[0]
    es.onerror?.(new Event('error'))
    cleanup()
    expect(es.close).toHaveBeenCalled()
  })

  it('passes parsed SSE events to the handler', () => {
    const events: SSEEvent[] = []
    connectSSE('/api/v1/events/stream', (e) => events.push(e))
    const es = MockEventSource.instances[0]
    es.onmessage?.(new MessageEvent('message', { data: '{"event":"delta","delta":"hi"}' }))
    expect(events).toEqual([{ type: 'delta', data: { event: 'delta', delta: 'hi' } }])
  })

  it('closes without reconnecting after a done event', () => {
    const onRetry = vi.fn()
    const onEvent = vi.fn()
    connectSSE('/api/v1/events/stream?query=test', onEvent, vi.fn(), {
      baseDelayMs: 100,
      onRetry,
    })
    const es = MockEventSource.instances[0]

    es.onmessage?.(new MessageEvent('message', { data: '{"type":"done","total":3}' }))
    es.onerror?.(new Event('error'))
    vi.advanceTimersByTime(1000)

    expect(onEvent).toHaveBeenCalledWith({
      type: 'done',
      data: { type: 'done', total: 3 },
    })
    expect(es.close).toHaveBeenCalled()
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

  it('collects SSE data lines and stops on done event', async () => {
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
  })

  it('uses API_BASE for the request URL', async () => {
    const encoder = new TextEncoder()
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: true,
      body: { getReader: () => makeReader([encoder.encode('data: {}\n\n')]) },
    })

    await fetchSSE('/tasks/stream', { foo: 'bar' })
    expect(globalThis.fetch).toHaveBeenCalledWith(
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
