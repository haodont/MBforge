export interface ProgressBarProps {
  value: number  // 0-100
  label?: string
  showPercent?: boolean
  color?: string
  height?: number
  style?: React.CSSProperties
}

export default function ProgressBar({ 
  value, 
  label, 
  showPercent = true, 
  color = 'var(--success)',
  height = 8,
  style 
}: ProgressBarProps) {
  const percent = Math.min(100, Math.max(0, value))

  return (
    <div style={{ width: '100%', ...style }}>
      {(label || showPercent) && (
        <div style={{ 
          display: 'flex', 
          justifyContent: 'space-between',
          marginBottom: '6px',
          fontSize: '12px',
        }}>
          {label && <span style={{ color: 'var(--text-secondary)' }}>{label}</span>}
          {showPercent && <span style={{ color: 'var(--text-muted)', fontVariantNumeric: 'tabular-nums' }}>{percent}%</span>}
        </div>
      )}
      <div style={{
        width: '100%',
        height: `${height}px`,
        background: 'var(--bg-elevated)',
        borderRadius: `${height / 2}px`,
        overflow: 'hidden',
      }}>
        <div style={{
          width: `${percent}%`,
          height: '100%',
          background: color,
          borderRadius: `${height / 2}px`,
          transition: 'width 0.3s ease',
        }} />
      </div>
    </div>
  )
}
