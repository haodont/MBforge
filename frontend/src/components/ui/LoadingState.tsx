/** Unified loading state — spinner, skeleton, or progress variants. */

import Spinner from './Spinner'
import Skeleton from './Skeleton'
import ProgressBar from './ProgressBar'

interface LoadingStateProps {
  variant?: 'spinner' | 'skeleton' | 'progress'
  message?: string
  /** Number of skeleton rows (skeleton variant only). */
  count?: number
  /** Progress 0-100 (progress variant only). */
  progress?: number
  progressLabel?: string
  className?: string
}

export function LoadingState({
  variant = 'spinner',
  message,
  count = 3,
  progress,
  progressLabel,
  className = '',
}: LoadingStateProps) {
  return (
    <div className={`loading-state loading-state--${variant} ${className}`}>
      {variant === 'spinner' && (
        <div className="loading-state-spinner">
          <Spinner />
          {message && <p className="loading-state-message">{message}</p>}
        </div>
      )}
      {variant === 'skeleton' && (
        <div className="loading-state-skeleton">
          {Array.from({ length: count }, (_, i) => (
            <Skeleton key={i} variant="text" />
          ))}
          {message && <p className="loading-state-message">{message}</p>}
        </div>
      )}
      {variant === 'progress' && (
        <div className="loading-state-progress">
          <ProgressBar value={progress ?? 0} showPercent color="var(--accent)" height={6} />
          {progressLabel && <p className="loading-state-message">{progressLabel}</p>}
          {message && <p className="loading-state-message loading-state-message--sub">{message}</p>}
        </div>
      )}
    </div>
  )
}
