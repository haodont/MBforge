import { useState, useCallback } from 'react'
import { showToast, dismissToast, toast, type ToastType, type ToastItem } from '../components/ui/Toast'

// Re-export
export type { ToastType, ToastItem }
export { showToast, dismissToast, toast }

export function useToast() {
  const [, setTick] = useState(0)
  const refresh = useCallback(() => setTick(t => t + 1), [])

  // 保留兼容的旧接口
  return {
    toasts: [],
    show: showToast,
    dismiss: dismissToast,
    success: (message: string, opts?: Partial<ToastItem>) => toast.success(message, opts),
    error: (message: string, opts?: Partial<ToastItem>) => toast.error(message, opts),
    info: (message: string, opts?: Partial<ToastItem>) => toast.info(message, opts),
    warning: (message: string, opts?: Partial<ToastItem>) => toast.warning(message, opts),
    refresh,
  }
}
