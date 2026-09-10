import type { ReactNode } from 'react'
import { useIsMobile, useIsTablet } from '../../styles/responsive'

export interface PageContainerProps {
  children: ReactNode
  noPadding?: boolean
  style?: React.CSSProperties
  className?: string
}

export default function PageContainer({ children, noPadding = false, style, className }: PageContainerProps) {
  const isMobile = useIsMobile()
  const isTablet = useIsTablet()

  const padding = noPadding
    ? 0
    : isMobile
    ? '16px'
    : isTablet
    ? '24px'
    : '32px'

  return (
    <div
      className={className}
      style={{
        flex: 1,
        minHeight: 0,
        padding,
        overflow: 'hidden',
        display: 'flex',
        flexDirection: 'column',
        ...style,
      }}
    >
       {children}
     </div>
  )
}
