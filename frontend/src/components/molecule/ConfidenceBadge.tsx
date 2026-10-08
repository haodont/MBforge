import Badge from '@/components/ui/Badge'
import type { BadgeTone } from '@/components/ui/Badge'

interface ConfidenceBadgeProps {
  value: number
}

export default function ConfidenceBadge({ value }: ConfidenceBadgeProps) {
  const pct = Math.round(value * 100)
  const tone: BadgeTone = pct >= 80 ? 'success' : pct >= 50 ? 'warning' : 'danger'
  return (
    <Badge tone={tone} dot>
      置信度 {pct}%
    </Badge>
  )
}
