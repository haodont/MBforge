/**
 * 置信度阈值滑块 — 业务专用 Slider。
 *
 * 用于：
 *   - CorrectionPanel 顶部（OCR 矫正流程的自动确认门槛）
 *
 * 设计：
 *   - 阈值越高 → 越少自动确认 → 越多人工复核
 *   - 阈值越低 → 越多自动确认 → 风险越大
 *   - 用户在矫正前调整即可，不必每次都重设
 *
 * 真实显示：
 *   "置信度阈值 ≥ 0.50 （仅高置信度自动确认）"
 */

import Slider from '@/components/ui/Slider'
import { useConfidenceThreshold, MIN_THRESHOLD, MAX_THRESHOLD, STEP } from '@/hooks/useConfidenceThreshold'

export interface ConfidenceThresholdSliderProps {
  /** 紧凑模式：去掉 label，节省空间 */
  compact?: boolean
  style?: React.CSSProperties
  className?: string
}

export default function ConfidenceThresholdSlider({
  compact = false,
  style,
  className,
}: ConfidenceThresholdSliderProps) {
  const [threshold, setThreshold] = useConfidenceThreshold()

  if (compact) {
    return (
      <div className={className} style={style}>
        <Slider
          value={threshold}
          onChange={setThreshold}
          min={MIN_THRESHOLD}
          max={MAX_THRESHOLD}
          step={STEP}
          formatValue={v => `≥ ${Math.round(v * 100)}%`}
          label="置信度阈值"
        />
      </div>
    )
  }

  return (
    <div
      className={className}
      style={{
        display: 'flex',
        flexDirection: 'column',
        gap: 6,
        padding: '10px 14px',
        background: 'var(--bg-base)',
        border: '1px solid var(--border)',
        borderRadius: 8,
        ...style,
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8 }}>
        <span style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-secondary)' }}>
          置信度阈值
        </span>
        <span
          style={{
            fontSize: 11,
            color: 'var(--text-muted)',
            fontVariantNumeric: 'tabular-nums',
          }}
        >
          仅 ≥ 阈值 的 OCR 结果自动确认
        </span>
      </div>
      <Slider
        value={threshold}
        onChange={setThreshold}
        min={MIN_THRESHOLD}
        max={MAX_THRESHOLD}
        step={STEP}
        formatValue={v => `${Math.round(v * 100)}%`}
      />
    </div>
  )
}
