import type { ReactNode } from 'react'

interface OverlayLayerProps {
  renderWidth: number
  renderHeight: number
  children: ReactNode
}

/** Absolutely positioned layer matching the rendered PDF page size. */
export default function OverlayLayer({
  renderWidth,
  renderHeight,
  children,
}: OverlayLayerProps) {
  return (
    <div
      style={{
        position: 'absolute',
        top: 0,
        left: '50%',
        width: renderWidth,
        height: renderHeight,
        transform: 'translateX(-50%)',
        pointerEvents: 'none',
        zIndex: 2,
      }}
    >
      {children}
    </div>
  )
}
