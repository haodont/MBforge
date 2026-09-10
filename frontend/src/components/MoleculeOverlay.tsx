import { memo, useMemo, useState } from 'react'
import type { ExtractionResult, DetectionBox } from '@/types'
import { pdfToCss } from '@/utils/pdf'

interface Props {
  /** MolDet 检测结果列表 */
  detections: ExtractionResult[]
  /** 渲染后的 canvas/页面宽度（CSS 像素） */
  renderWidth: number
  /** 渲染后的 canvas/页面高度（CSS 像素） */
  renderHeight: number
  /** 页面原始高度（PDF points, 72 DPI） */
  originalHeight: number
  /** 页面原始宽度（PDF points, 72 DPI） */
  originalWidth: number
  /** 缩放比例 */
  scale: number
  /** 当前页码（用于验证） */
  currentPage?: number
  /** 选中的检测索引 */
  selectedIndex?: number
  /** 选中检测回调（用于已识别条目） */
  onSelect?: (index: number, detection?: ExtractionResult) => void
  /** 触发完整识别（用于 quick-scan bbox-only 条目） */
  onRecognize?: () => void
  /** 是否正在识别中 */
  isRecognizing?: boolean
}

/** 覆盖层标签：当前读源只有裁图路径，退化为逐页分子序号；有身份字段时优先显示。 */
function moleculeLabel(d: ExtractionResult | undefined): string {
  if (!d) return '分子'
  const identity = d.name || d.smiles || d.esmiles
  if (identity) return identity.length > 24 ? `${identity.slice(0, 24)}...` : identity
  const match = /_mol_(\d+)/.exec(d.mol_img_path ?? '')
  return match ? `分子 ${Number(match[1]) + 1}` : '分子'
}

/** 置信度颜色；0 表示没有置信度数据（当前 source_evidence 只带框），用中性色 */
function confColor(conf: number): string {
  if (!(conf > 0)) return '#6b7280'
  if (conf >= 0.8) return 'var(--success)'
  if (conf >= 0.5) return 'var(--warning)'
  return 'var(--danger)'
}

const MoleculeOverlay = memo(function MoleculeOverlay({
  detections,
  renderWidth,
  renderHeight,
  originalHeight,
  originalWidth,
  scale,

  selectedIndex,
  onSelect,
  onRecognize,
  isRecognizing,
}: Props) {
  // 将 PDF bbox 转换为 CSS 像素坐标
  const boxes: DetectionBox[] = useMemo(() => {
    return detections
      .filter(d => d.bbox_pdf != null && d.bbox_pdf[2] > d.bbox_pdf[0] && d.bbox_pdf[3] > d.bbox_pdf[1])
      .map((d) => {
        const bboxPdf = d.bbox_pdf as [number, number, number, number]
        const bbox = pdfToCss(bboxPdf, originalHeight, scale, originalWidth, renderWidth)
        return {
          x1: bbox.x,
          y1: bbox.y,
          x2: bbox.x + bbox.w,
          y2: bbox.y + bbox.h,
          conf: d.moldet_conf,
          result: d,
        }
      })
  }, [detections, originalHeight, originalWidth, renderWidth, scale])

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
      {boxes.map((box, i) => {
        const isSelected = selectedIndex === i
        const isHovered = hoveredIdx === i
        const color = confColor(box.conf)
        const boxW = box.x2 - box.x1
        const boxH = box.y2 - box.y1
        const isQuickScan = box.result?.is_quick_scan ?? false
        const label = moleculeLabel(box.result)
        const ctx = box.result?.context_text || ''

        return (
          <div
            key={`mol-${box.result?.esmiles || 'none'}-${i}`}
            data-evidence-id={box.result?.evidence_id}
            style={{
              position: 'absolute',
              left: box.x1,
              top: box.y1,
              width: boxW,
              height: boxH,
              border: `2px ${isQuickScan ? 'dashed' : 'solid'} ${color}`,
              borderRadius: '3px',
              background: isSelected ? 'rgba(59,130,246,0.1)' : 'transparent',
              cursor: isRecognizing ? 'wait' : 'pointer',
              pointerEvents: isRecognizing ? 'none' : 'auto',
              opacity: isQuickScan ? 0.85 : 1,
              transition: 'background-color 0.15s, opacity 0.15s',
            }}
            onClick={() => {
              if (isQuickScan) {
                onRecognize?.()
              } else {
                onSelect?.(i, box.result)
              }
            }}
            onMouseEnter={() => setHoveredIdx(i)}
            onMouseLeave={() => setHoveredIdx(null)}
          >
            {/* 左上角标签：识别状态或分子标识 */}
            <div style={{
              position: 'absolute',
              top: -24,
              left: 0,
              display: 'flex',
              gap: '4px',
              alignItems: 'center',
              whiteSpace: 'nowrap',
              fontSize: '10px',
              fontFamily: 'monospace',
              pointerEvents: 'none',
            }}>
              <span style={{
                background: isQuickScan ? 'var(--bg-surface)' : color,
                color: isQuickScan ? 'var(--text-secondary)' : 'var(--text-on-accent)',
                padding: '1px 5px',
                borderRadius: '3px',
                border: isQuickScan ? '1px solid var(--border)' : 'none',
                fontWeight: 600,
                fontSize: '9px',
              }}>
                {isQuickScan ? '未识别' : label}
              </span>
            </div>
            {/* Hover tooltip: 上下文文本 */}
            {isHovered && ctx && (
              <div style={{
                position: 'absolute',
                top: boxH + 6,
                left: 0,
                maxWidth: '300px',
                padding: '6px 10px',
                background: 'var(--bg-elevated)',
                color: 'var(--text-secondary)',
                fontSize: '10px',
                lineHeight: 1.4,
                borderRadius: '6px',
                border: '1px solid var(--border)',
                boxShadow: '0 4px 12px rgba(0,0,0,0.2)',
                zIndex: 100,
                pointerEvents: 'none',
                whiteSpace: 'pre-wrap',
                wordBreak: 'break-word',
              }}>
                {ctx.length > 200 ? ctx.slice(0, 200) + '...' : ctx}
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
})

export default MoleculeOverlay
