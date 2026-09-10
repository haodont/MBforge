/** Inline error state with optional retry and dismiss buttons. */

import Button from './Button'
import { XIcon } from '../icons'

interface ErrorStateProps {
  error: string | Error
  onRetry?: () => void
  onDismiss?: () => void
  compact?: boolean
  className?: string
}

export function ErrorState({
  error,
  onRetry,
  onDismiss,
  compact = false,
  className = '',
}: ErrorStateProps) {
  const message = typeof error === 'string' ? error : error.message

  return (
    <div className={`error-state${compact ? ' error-state--compact' : ''} ${className}`}>
      <div className="error-state-icon" aria-hidden>
        <XIcon size={compact ? 14 : 18} />
      </div>
      <div className="error-state-body">
        <p className="error-state-message">{message}</p>
        <div className="error-state-actions">
          {onRetry && (
            <Button variant="secondary" size="sm" onClick={onRetry}>
              Retry
            </Button>
          )}
          {onDismiss && (
            <Button variant="ghost" size="sm" onClick={onDismiss}>
              Dismiss
            </Button>
          )}
        </div>
      </div>
    </div>
  )
}
