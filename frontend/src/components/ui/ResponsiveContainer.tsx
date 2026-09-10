/**
 * 响应式布局工具组件。
 */
import type { ReactNode, CSSProperties } from 'react'
import { useIsMobile, useIsTablet, useIsDesktop } from '../../styles/responsive'

// ============================================================================
// ResponsiveLayout - 自适应布局容器
// ============================================================================

type Direction = 'row' | 'column'

export interface ResponsiveLayoutProps {
  children: ReactNode
  /** 移动端布局方向（默认 column） */
  mobileDirection?: Direction
  /** 平板布局方向（默认 row） */
  tabletDirection?: Direction
  /** 桌面端布局方向（默认 row） */
  desktopDirection?: Direction
  gap?: number | string
  style?: CSSProperties
  className?: string
}

/**
 * 根据屏幕尺寸自动调整布局方向。
 * 移动端默认纵向，平板/桌面默认横向。
 */
export function ResponsiveLayout({
  children,
  mobileDirection = 'column',
  tabletDirection = 'row',
  desktopDirection = 'row',
  gap = 12,
  style,
  className,
}: ResponsiveLayoutProps) {
  const isMobile = useIsMobile()
  const isTablet = useIsTablet()

  const direction: Direction = isMobile
    ? mobileDirection
    : isTablet
    ? tabletDirection
    : desktopDirection

  return (
    <div
      className={className}
      style={{
        display: 'flex',
        flexDirection: direction,
        gap,
        ...style,
      }}
    >
      {children}
    </div>
  )
}

// ============================================================================
// Show / Hide - 响应式显隐
// ============================================================================

export interface ShowOnProps {
  children: ReactNode
  /** 在哪些断点上显示 */
  on: ('mobile' | 'tablet' | 'desktop')[]
}

export function ShowOn({ children, on }: ShowOnProps) {
  const isMobile = useIsMobile()
  const isTablet = useIsTablet()
  const isDesktop = useIsDesktop()

  const visible =
    (on.includes('mobile') && isMobile) ||
    (on.includes('tablet') && isTablet && !isMobile) ||
    (on.includes('desktop') && isDesktop)

  if (!visible) return null
  return <>{children}</>
}

export interface HideOnProps {
  children: ReactNode
  /** 在哪些断点上隐藏 */
  on: ('mobile' | 'tablet' | 'desktop')[]
}

export function HideOn({ children, on }: HideOnProps) {
  const isMobile = useIsMobile()
  const isTablet = useIsTablet()
  const isDesktop = useIsDesktop()

  const hidden =
    (on.includes('mobile') && isMobile) ||
    (on.includes('tablet') && isTablet && !isMobile) ||
    (on.includes('desktop') && isDesktop)

  if (hidden) return null
  return <>{children}</>
}

// ============================================================================
// ResponsiveGrid - 响应式网格
// ============================================================================

export interface ResponsiveGridProps {
  children: ReactNode
  /** 移动端列数（默认 1） */
  mobileColumns?: number
  /** 平板列数（默认 2） */
  tabletColumns?: number
  /** 桌面列数（默认 3） */
  desktopColumns?: number
  gap?: number | string
  style?: CSSProperties
  className?: string
}

export function ResponsiveGrid({
  children,
  mobileColumns = 1,
  tabletColumns = 2,
  desktopColumns = 3,
  gap = 16,
  style,
  className,
}: ResponsiveGridProps) {
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
