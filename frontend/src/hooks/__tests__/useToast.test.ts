import { describe, it, expect, beforeEach, vi } from 'vitest'
import { renderHook } from '@testing-library/react'
import {
  showToast,
  dismissToast,
  useToast as useToastState,
  type ToastItem,
} from '@/components/ui/Toast'

function currentToasts(): ToastItem[] {
  const { result, rerender } = renderHook(() => useToastState())
  rerender()
  return result.current.toasts
}

describe('toast store', () => {
  beforeEach(() => {
    for (const t of currentToasts()) dismissToast(t.id)
  })

  it('showToast adds a toast and dismissToast removes it, firing onClose', () => {
    const onClose = vi.fn()
    const id = showToast({ message: 'hello', type: 'success', duration: 0, onClose })

    expect(currentToasts()).toEqual([
      expect.objectContaining({ id, message: 'hello', type: 'success' }),
    ])

    dismissToast(id)
    expect(onClose).toHaveBeenCalledTimes(1)
    expect(currentToasts()).toEqual([])
  })
})
