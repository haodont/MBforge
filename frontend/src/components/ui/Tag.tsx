import { TONE_COLORS, type StatusTone } from '../../styles/tokens'

export interface TagProps {
  children: React.ReactNode
  tone?: StatusTone
  style?: React.CSSProperties
  className?: string
  onClick?: () => void
}

/**
 * Tag 标签/芯片组件。
 *
 * 替代 notes/TagPill.tsx 的功能，作为 ui/ 层统一原子组件。
 */
export default function Tag({
  children,
  tone = 'neutral',
  style,
  className,
  onClick,
}: TagProps) {
  const colors = TONE_COLORS[tone]

  return (
    <span
      className={className}
      onClick={onClick}
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 4,
        padding: '2px 8px',
        borderRadius: 4,
        fontSize: 12,
        fontWeight: 500,
        color: colors.color,
        background: colors.bg,
        border: `1px solid ${colors.border}`,
        cursor: onClick ? 'pointer' : 'default',
        userSelect: 'none',
        ...style,
      }}
    >
      {children}
    </span>
  )
}
