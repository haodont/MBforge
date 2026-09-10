import { useEffect, useRef } from 'react'

export interface UsePollingOptions<T> {
  /** Polling interval in milliseconds. */
  intervalMs: number
  /** Async function that produces the polled value. */
  fetcher: () => Promise<T>
  /** Invoked with each fetched value. Errors are caught and reported via `onError`. */
  onResult?: (value: T) => void
  /** Invoked when the fetcher rejects. Defaults to a no-op so polling survives transient failures. */
  onError?: (err: unknown) => void
  /** When false, polling is suspended. Defaults to true. */
  enabled?: boolean
  /**
   * When true (default), polling pauses while `document.hidden` and resumes
   * on visibilitychange. Set to false for hooks that must keep polling in
   * background tabs (e.g., ingest notifications are intentionally silent).
   */
  pauseWhenHidden?: boolean
}

/**
 * Shared interval-driven polling effect. Used by `useIngestNotifications`
 * and `useModelDownloadStatus` to keep their timer/lifecycle logic in
 * one place.
 */
export function usePolling<T>({
  intervalMs,
  fetcher,
  onResult,
  onError,
  enabled = true,
  pauseWhenHidden = true,
}: UsePollingOptions<T>): void {
  const fetcherRef = useRef(fetcher)
  const onResultRef = useRef(onResult)
  const onErrorRef = useRef(onError)
  const generationRef = useRef(0)

  useEffect(() => {
    fetcherRef.current = fetcher
    onResultRef.current = onResult
    onErrorRef.current = onError
  })

  useEffect(() => {
    if (!enabled) return
    const generation = ++generationRef.current
    let timer: ReturnType<typeof setInterval> | null = null

    const poll = async () => {
      if (generationRef.current !== generation) return
      if (pauseWhenHidden && typeof document !== 'undefined' && document.hidden) return
      try {
        const value = await fetcherRef.current()
        if (generationRef.current !== generation) return
        onResultRef.current?.(value)
      } catch (err) {
        if (generationRef.current !== generation) return
        onErrorRef.current?.(err)
      }
    }

    const start = () => {
      if (timer != null) return
      void poll()
      timer = setInterval(poll, intervalMs)
    }
    const stop = () => {
      if (timer == null) return
      clearInterval(timer)
      timer = null
    }

    if (pauseWhenHidden && typeof document !== 'undefined') {
      const onVisibility = () => {
        if (document.hidden) stop()
        else start()
      }
      start()
      document.addEventListener('visibilitychange', onVisibility)
      return () => {
        generationRef.current = generation + 1
        stop()
        document.removeEventListener('visibilitychange', onVisibility)
      }
    }

    start()
    return () => {
      generationRef.current = generation + 1
      stop()
    }
  }, [enabled, intervalMs, pauseWhenHidden])
}