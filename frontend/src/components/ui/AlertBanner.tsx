import { TONE_COLORS, type StatusTone } from '../../styles/tokens'

export type AlertVariant = 'success' | 'danger' | 'info' | 'warning' | 'error'

export interface AlertBannerProps {
  message: string
  variant?: AlertVariant
  onDismiss?: () => void
  style?: React.CSSProperties
  className?: string
}

/** Map AlertVariant to TONE_COLORS key (some need to be remapped) */
const toneMap: Record<AlertVariant, StatusTone> = {
  success: 'success',
  danger:  'error',    // 'error' provides more vibrant red than 'danger'
  info:    'info',
  warning: 'warning',
  error:   'error',
}

export default function AlertBanner({ message, variant = 'info', onDismiss, style, className }: AlertBannerProps) {
  const v = TONE_COLORS[toneMap[variant]]

  return (
    <div
      className={className}
      style={{
        padding: '10px 16px',
        background: v.bg,
        border: `1px solid ${v.border}`,
        borderRadius: '6px',
        color: v.color,
        fontSize: '13px',
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        marginBottom: '12px',
        ...style,
      }}
    >
      <span>{message}</span>
      {onDismiss && (
        <button
          onClick={onDismiss}
          style={{
            background: 'none',
            border: 'none',
            color: v.color,
            cursor: 'pointer',
            fontSize: '16px',
            padding: '0 4px',
            lineHeight: 1,
          }}
        >
          ×
        </button>
      )}
    </div>
  )
}
