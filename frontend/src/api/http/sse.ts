/** SSE (Server-Sent Events) client for real-time streaming from FastAPI backend. */

import { apiUrl } from './_utils'
import { logger } from '@/utils/logger'

export interface SSEEvent {
  type: string
  data: Record<string, unknown>
}

export interface ConnectSSEOptions {
  /** Maximum consecutive reconnect attempts before giving up. Default: 5. */
  maxRetries?: number
  /** Initial backoff in milliseconds; doubled each subsequent retry. Default: 1000. */
  baseDelayMs?: number
  /** Optional hook fired on each reconnect attempt (useful for UI status). */
  onRetry?: (attempt: number, delayMs: number) => void
}

/**
 * Connect to a server-sent-events endpoint and stream events to `onEvent`.
 *
 * Built-in exponential reconnect: when the EventSource closes or hits an
 * `onerror`, the client waits `baseDelayMs * 2^attempt` (capped at 30 s) and
 * reopens. After `maxRetries` failed attempts the connection is reported to
 * `onError` once and the returned cleanup function becomes a no-op.
 *
 * Why this exists: a flaky loopback mid-stream used to silently truncate
 * streamed responses. The backoff keeps transient drops survivable while
 * bounded so we don't thrash.
 */
export function connectSSE(
  path: string,
  onEvent: (event: SSEEvent) => void,
  onError?: (error: Event) => void,
  options: ConnectSSEOptions = {},
): () => void {
  const maxRetries = options.maxRetries ?? 5
  const baseDelayMs = options.baseDelayMs ?? 1000
  const MAX_DELAY_MS = 30_000

  let attempt = 0
  let es: EventSource | null = null
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null
  let disposed = false
  let gaveUp = false
  let completed = false

  function open() {
    if (disposed || gaveUp || completed) return
    const url = apiUrl(path)
    es = new EventSource(url)
    es.onopen = () => {
      attempt = 0
    }
    es.onmessage = (event) => {
      try {
        const data = JSON.parse(String(event.data)) as Record<string, unknown>
        const rawType = data.event ?? data.type
        onEvent({ type: typeof rawType === 'string' ? rawType : 'message', data })
        if (rawType === 'done') {
          // A completed stream must not enter the reconnect path. Some
          // browsers emit `onerror` while EventSource is being closed after
          // the server's final event; treating that as a transient failure
          // would replay the whole search stream.
          completed = true
          es?.close()
          es = null
        }
      } catch {
        onEvent({ type: 'raw', data: { text: String(event.data) } })
      }
    }
    es.onerror = (err) => {
      logger.error('[SSE] Error:', err)
      // EventSource auto-retries at the browser level, but we layer our own
      // backoff + cap on top so an offline backend doesn't loop forever.
      if (disposed || completed) return
      if (attempt >= maxRetries) {
        gaveUp = true
        es?.close()
        onError?.(err)
        return
      }
      const delay = Math.min(MAX_DELAY_MS, baseDelayMs * 2 ** attempt)
      attempt += 1
      options.onRetry?.(attempt, delay)
      es?.close()
      es = null
      reconnectTimer = setTimeout(() => {
        reconnectTimer = null
        open()
      }, delay)
    }
  }

  open()

  return () => {
    disposed = true
    if (reconnectTimer != null) {
      clearTimeout(reconnectTimer)
      reconnectTimer = null
    }
    es?.close()
    es = null
  }
}

export async function fetchSSE<T = unknown>(
  path: string,
  params?: Record<string, string>,
  signal?: AbortSignal,
): Promise<T[]> {
  if (signal?.aborted) {
    throw new Error('SSE fetch aborted')
  }
  const base = typeof window !== 'undefined' ? window.location.href : 'http://localhost'
  const url = new URL(apiUrl(path), base)
  if (params) Object.entries(params).forEach(([k, v]) => url.searchParams.set(k, v))
  const resp = await fetch(url.toString(), { signal })
  if (!resp.ok) throw new Error(`SSE fetch failed: ${resp.status}`)
  const reader = resp.body?.getReader()
  if (!reader) return []
  if (signal?.aborted) {
    reader.cancel().catch(() => {})
    throw new Error('SSE fetch aborted')
  }

  const abortReader = () => {
    reader.cancel().catch(() => {})
  }
  signal?.addEventListener('abort', abortReader)

  const decoder = new TextDecoder()
  const events: T[] = []
  let buffer = ''
  let finished = false
  try {
    for (;;) {
      const { done, value } = await reader.read()
      if (done || finished) break
      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n')
      buffer = lines.pop() || ''
      for (const line of lines) {
        if (line.startsWith('data: ')) {
          try {
            const data = JSON.parse(line.slice(6)) as Record<string, unknown>
            if (data.type === 'done' || data.event === 'done') {
              finished = true
              break
            }
            events.push(data as T)
          } catch {
            // malformed JSON line — skip
          }
        }
      }
    }
  } finally {
    signal?.removeEventListener('abort', abortReader)
    reader.cancel().catch(() => {})
  }
  return events
}
