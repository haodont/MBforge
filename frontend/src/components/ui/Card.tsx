import type { ReactNode, MouseEvent } from 'react'

export interface CardProps {
  children: ReactNode
  padding?: number | string
  hoverable?: boolean
  onClick?: (e: MouseEvent<HTMLDivElement>) => void
  style?: React.CSSProperties
  className?: string
  title?: string
}

/**
 * Card 卡片容器。
 *
 * 视觉样式由 styles/ui.css 的 .ui-card 类承载；padding 为调用方动态值，保留内联。
 */
export default function Card({ children, padding = '20px', hoverable = false, onClick, style, className, title }: CardProps) {
  const interactive = hoverable || onClick !== undefined
  const cls = ['ui-card', interactive && 'ui-card--hoverable', className]
    .filter(Boolean)
    .join(' ')

  return (
    <div className={cls} onClick={onClick} style={{ padding, ...style }} title={title}>
      {children}
    </div>
  )
}
