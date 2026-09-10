import type { ReactNode } from 'react'

export type BadgeTone = 'success' | 'warning' | 'danger' | 'info' | 'neutral' | 'loading'
export type BadgeVariant = 'neutral' | 'success' | 'warning' | 'danger' | 'info'

export interface BadgeProps {
  children: ReactNode
  /** New API: semantic tone used by the UI upgrade. */
  tone?: BadgeTone
  /** New API: size. */
  size?: 'sm' | 'md'
  /** Legacy API: variant alias for tone. Prefer `tone`. */
  variant?: BadgeVariant
  /** Legacy API: show a left dot. */
  dot?: boolean
  /** Native title attribute (hover tooltip). */
  title?: string
  className?: string
  style?: React.CSSProperties
}

/** tone → ui.css 修饰类；loading 复用 neutral 外观。 */
function effectiveTone(tone: BadgeTone | undefined, variant: BadgeVariant | undefined): BadgeVariant {
  if (tone) return tone === 'loading' ? 'neutral' : tone
  return variant ?? 'neutral'
}

export default function Badge({
  children,
  tone,
  size = 'sm',
  variant,
  dot = false,
  title,
  className,
  style,
}: BadgeProps) {
  const cls = [
    'ui-badge',
    `ui-badge--${effectiveTone(tone, variant)}`,
    `ui-badge--${size}`,
    dot && 'ui-badge--dot',
    className,
  ]
    .filter(Boolean)
    .join(' ')

  return (
    <span className={cls} style={style} title={title}>
      {dot && <span className="ui-badge__dot" />}
      {children}
    </span>
  )
}
