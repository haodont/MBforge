/**
 * Front-end client error reporter — pushes caught errors to the backend
 * `/api/v1/diagnostics/errors` endpoint so they surface alongside server-side
 * errors in the same ring buffer.
 *
 * Batching strategy:
 * - In-memory `QUEUE` collects raw error items as they happen.
 * - A 1.5 s debounce timer coalesces a burst into a single POST.
 * - `fetch(..., { keepalive: true })` lets the request survive a tab close
 *   for the in-flight browser window — by the time the user closes the tab,
 *   the queued flush is already on the wire.
 */

import { apiUrl } from '@/api/http/_utils'

const DIAGNOSTICS_URL = apiUrl('/diagnostics/errors')
const FLUSH_DELAY_MS = 1500

interface QueuedError {
  message: string
  name?: string
  stack?: string
  category: string
  severity: 'ERROR' | 'FATAL' | 'WARNING'
  context: Record<string, unknown>
  timestamp: number
}

const QUEUE: QueuedError[] = []
let flushTimer: ReturnType<typeof setTimeout> | null = null

export function reportClientError(
  err: Error | string,
  context: Record<string, unknown> = {},
): void {
  const message = err instanceof Error ? err.message : err
  const stack = err instanceof Error ? (err.stack ?? undefined) : undefined
  const name = err instanceof Error ? err.name : undefined
  QUEUE.push({
    message,
    name,
    stack,
    category: 'client',
    severity: 'ERROR',
    context,
    timestamp: Date.now() / 1000,
  })
  if (flushTimer == null) {
    flushTimer = setTimeout(flush, FLUSH_DELAY_MS)
  }
}

async function flush(): Promise<void> {
  flushTimer = null
  if (QUEUE.length === 0) return
  const batch = QUEUE.splice(0, QUEUE.length)
  try {
    await fetch(DIAGNOSTICS_URL, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ errors: batch }),
      keepalive: true,
    })
  } catch {
    // Best-effort: dropped errors are still captured in console + ErrorBoundary UI.
  }
}

/** Hook returning a stable `reportClientError` reference for use in components. */
export function useErrorReport(): (err: Error | string, context?: Record<string, unknown>) => void {
  return reportClientError
}
