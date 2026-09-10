import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { usePolling } from '../usePolling'

describe('usePolling', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })
  afterEach(() => {
    vi.useRealTimers()
  })

  it('calls fetcher immediately and on every interval tick', async () => {
    const fetcher = vi.fn().mockResolvedValue('ok')

    renderHook(() => usePolling({ intervalMs: 1000, fetcher }))

    await act(async () => {
      await vi.advanceTimersByTimeAsync(0)
    })
    expect(fetcher).toHaveBeenCalledTimes(1)

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000)
    })
    expect(fetcher).toHaveBeenCalledTimes(2)
  })

  it('invokes onResult with the resolved value', async () => {
    const onResult = vi.fn()
    const fetcher = vi.fn().mockResolvedValue('value')

    renderHook(() => usePolling({ intervalMs: 1000, fetcher, onResult }))

    await act(async () => {
      await vi.advanceTimersByTimeAsync(0)
    })

    expect(onResult).toHaveBeenCalledWith('value')
  })

  it('stops polling on unmount', async () => {
    const fetcher = vi.fn().mockResolvedValue('ok')

    const { unmount } = renderHook(() => usePolling({ intervalMs: 1000, fetcher }))
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0)
    })
    expect(fetcher).toHaveBeenCalledTimes(1)

    unmount()
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000)
    })
    expect(fetcher).toHaveBeenCalledTimes(1)
  })

  it('does not poll when enabled is false', async () => {
    const fetcher = vi.fn().mockResolvedValue('ok')

    renderHook(() => usePolling({ intervalMs: 1000, fetcher, enabled: false }))

    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000)
    })
    expect(fetcher).not.toHaveBeenCalled()
  })
})