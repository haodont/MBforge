interface ConfidenceBadgeProps {
  value: number
}

export default function ConfidenceBadge({ value }: ConfidenceBadgeProps) {
  const pct = Math.round(value * 100)
  const color = pct >= 80 ? 'var(--success)' : pct >= 50 ? 'var(--warning)' : 'var(--danger)'
  return (
    <div className="mol-confidence-badge" style={{ borderColor: color, color }}>
      <span className="mol-confidence-dot" style={{ background: color }} />
      置信度 {pct}%
    </div>
  )
}
