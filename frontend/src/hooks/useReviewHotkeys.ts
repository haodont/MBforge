import { useEffect } from 'react'

interface ReviewHotkeyActions {
  onNext: () => void
  onPrevious: () => void
  onConfirm: () => void
  onReject: () => void
}

/** Keyboard navigation for the focused review item. */
export function useReviewHotkeys(enabled: boolean, actions: ReviewHotkeyActions): void {
  useEffect(() => {
    if (!enabled) return
    const handleKeyDown = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null
      if (target && (target.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName))) return
      if (event.key === 'j' || event.key === 'ArrowDown') {
        event.preventDefault()
        actions.onNext()
      } else if (event.key === 'k' || event.key === 'ArrowUp') {
        event.preventDefault()
        actions.onPrevious()
      } else if (event.key === 'c') {
        event.preventDefault()
        actions.onConfirm()
      } else if (event.key === 'x') {
        event.preventDefault()
        actions.onReject()
      }
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [actions, enabled])
}
