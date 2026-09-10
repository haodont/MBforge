import { memo, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import type { OcrBlock } from '@/api/http/pdf'
import { pdfToCss } from '@/utils/pdf'

interface Props {
  blocks: OcrBlock[]
  renderWidth: number
  renderHeight: number
  originalHeight: number
  originalWidth: number
  scale: number
  page?: number
  selectedIndex?: number
  onSelect?: (index: number, block?: OcrBlock) => void
  onHover?: (index: number | null) => void
}

/** 块类型颜色映射 */
function blockTypeColor(type: string): string {
  switch (type) {
    case 'text': return '#2563eb'
    case 'image': return '#16a34a'
    case 'table': return '#f59e0b'
    case 'formula': return '#9333ea'
    case 'chart': return '#dc2626'
    case 'header': return '#64748b'
    case 'footer': return '#64748b'
    case 'seal': return '#0891b2'
    default: return '#6b7280'
  }
}

/** Block type labels (i18n) */
function blockTypeLabel(type: string, t: (key: string) => string): string {
  const map: Record<string, string> = {
    text: t('ocr.block.text'),
    image: t('ocr.block.image'),
    table: t('ocr.block.table'),
    formula: t('ocr.block.formula'),
    chart: t('ocr.block.chart'),
    header: t('ocr.block.header'),
    footer: t('ocr.block.footer'),
    seal: t('ocr.block.seal'),
  }
  return map[type] || type
}

const OcrOverlay = memo(function OcrOverlay({
  blocks,
  renderWidth,
  renderHeight,
  originalHeight,
  originalWidth,
  scale,
  page,
  selectedIndex,
  onSelect,
  onHover,
}: Props) {
  const { t } = useTranslation()
  const boxes = useMemo(() => {
    return blocks
      .map((block, i) => ({ block, originalIndex: i }))
      .filter(({ block }) => page == null || block.page === page)
      .map(({ block, originalIndex }) => {
        const bbox = pdfToCss(block.bbox, originalHeight, scale, originalWidth, renderWidth)
        return {
          index: originalIndex,
          block,
          ...bbox,
        }
      })
  }, [blocks, originalHeight, originalWidth, renderWidth, scale, page])

  const [hoveredIdx, setHoveredIdx] = useState<number | null>(null)

  if (boxes.length === 0) return null

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
      {boxes.map((box) => {
        const isSelected = selectedIndex === box.index
        const isHovered = hoveredIdx === box.index
        const color = blockTypeColor(box.block.block_type)
        const label = blockTypeLabel(box.block.block_type, t)

        return (
          <div
            key={box.index}
            data-evidence-id={box.block.evidence_id}
            style={{
              position: 'absolute',
              left: box.x,
              top: box.y,
              width: box.w,
              height: box.h,
              border: `2px solid ${color}`,
              borderRadius: '2px',
              background: isSelected ? `${color}20` : isHovered ? `${color}10` : 'transparent',
              cursor: 'pointer',
              pointerEvents: 'auto',
              transition: 'background-color 0.12s ease',
            }}
            onClick={() => {
              onSelect?.(box.index, box.block)
            }}
            onMouseEnter={() => {
              setHoveredIdx(box.index)
              onHover?.(box.index)
            }}
            onMouseLeave={() => {
              setHoveredIdx(null)
              onHover?.(null)
            }}
          >
            {/* 类型标签 */}
            <div style={{
              position: 'absolute',
              top: -20,
              left: 0,
              display: 'flex',
              gap: '3px',
              alignItems: 'center',
              whiteSpace: 'nowrap',
              fontSize: '10px',
              pointerEvents: 'none',
            }}>
              <span style={{
                background: color,
                color: 'var(--text-on-accent)',
                padding: '1px 4px',
                borderRadius: '2px',
                fontWeight: 600,
                fontSize: '9px',
              }}>
                {label}
              </span>
            </div>
          </div>
        )
      })}
    </div>
  )
})

export default OcrOverlay
