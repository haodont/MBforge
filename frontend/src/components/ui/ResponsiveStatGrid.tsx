/**
 * 响应式统计卡片网格。
 *
 * - 移动端（< 768px）：2 列
 * - 平板（< 1024px）：2 列
 * - 桌面（≥ 1024px）：4 列
 */
import type { ReactNode, CSSProperties } from 'react'
import { useIsMobile, useIsTablet } from '../../styles/responsive'

export interface ResponsiveStatGridProps {
  children: ReactNode
  /** 移动端列数（默认 2） */
  mobileColumns?: number
  /** 平板列数（默认 2） */
  tabletColumns?: number
  /** 桌面列数（默认 4） */
  desktopColumns?: number
  gap?: number | string
  style?: CSSProperties
  className?: string
}

export default function ResponsiveStatGrid({
  children,
  mobileColumns = 2,
  tabletColumns = 2,
  desktopColumns = 4,
  gap = 16,
  style,
  className,
}: ResponsiveStatGridProps) {
  const isMobile = useIsMobile()
  const isTablet = useIsTablet()

  const columns = isMobile
    ? mobileColumns
    : isTablet
    ? tabletColumns
    : desktopColumns

  return (
    <div
      className={className}
      style={{
        display: 'grid',
        gridTemplateColumns: `repeat(${columns}, 1fr)`,
        gap,
        ...style,
      }}
    >
      {children}
    </div>
  )
}
