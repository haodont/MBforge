import { pdfToCss } from '@/utils/pdf'

export default function LocationHighlight({
  bbox,
  pageInfo,
}: {
  bbox: [number, number, number, number]
  pageInfo: {
    width: number
    height: number
    originalWidth: number
    originalHeight: number
    scale: number
  }
}) {
  const box = pdfToCss(
    bbox,
    pageInfo.originalHeight,
    pageInfo.scale,
    pageInfo.originalWidth,
    pageInfo.width,
  )
  return (
    <div
      aria-label="Deep-linked molecule location"
      style={{
        position: 'absolute',
        top: 0,
        left: '50%',
        width: pageInfo.width,
        height: pageInfo.height,
        transform: 'translateX(-50%)',
        pointerEvents: 'none',
        zIndex: 3,
      }}
    >
      <div
        style={{
          position: 'absolute',
          left: box.x,
          top: box.y,
          width: box.w,
          height: box.h,
          border: '3px solid var(--accent)',
          borderRadius: 4,
          boxShadow: '0 0 0 3px color-mix(in srgb, var(--accent) 24%, transparent)',
        }}
      />
    </div>
  )
}
