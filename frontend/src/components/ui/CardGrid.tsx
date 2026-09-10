import type { ReactNode } from 'react'
import { useIsMobile } from '../../styles/responsive'

export interface CardGridProps {
  children: ReactNode
  minWidth?: number
  /** 移动端最小宽度（默认无 minmax 限制） */
  mobileMinWidth?: number
  gap?: number
  style?: React.CSSProperties
  className?: string
}

export default function CardGrid({ children, minWidth = 280, mobileMinWidth, gap = 16, style, className }: CardGridProps) {
  const isMobile = useIsMobile()
  const effectiveMinWidth = isMobile ? (mobileMinWidth ?? minWidth) : minWidth

  return (
    <div
      className={className}
      style={{
        display: 'grid',
        gridTemplateColumns: `repeat(auto-fill, minmax(${effectiveMinWidth}px, 1fr))`,
        gap,
        ...style,
      }}
    >
      {children}
    </div>
  )
}
