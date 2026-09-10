import { useEffect, useState } from 'react'

export type ProgressStatus = 'normal' | 'success' | 'error' | 'warning'
export type ProgressType = 'line' | 'circle'

export interface ProgressProps {
  /** 进度（0-100）*/
  value: number
  /** 最大值（默认 100）*/
  max?: number
  /** 状态 */
  status?: ProgressStatus
  /** 类型 */
  type?: ProgressType
  /** 显示文字 */
  showText?: boolean
  /** 自定义格式化 */
  format?: (percent: number) => string
  /** 线条宽度（line 模式）*/
  strokeWidth?: number
  /** 圆形直径（circle 模式）*/
  size?: number
  /** 是否显示动画 */
  animated?: boolean
  /** 自动增加（demo 用）*/
  autoIncrement?: boolean
  style?: React.CSSProperties
  className?: string
}

const colorMap: Record<ProgressStatus, string> = {
  normal: 'var(--accent)',
  success: 'var(--success)',
  error: 'var(--danger)',
  warning: 'var(--warning)',
}

/**
 * Progress 进度条。
 *
 * 支持 line（线形）和 circle（圆形）两种类型。
 * 比 ProgressBar 更通用，支持状态色、文字、动画。
 */
export default function Progress({
  value,
  max = 100,
  status = 'normal',
  type = 'line',
  showText = true,
  format,
  strokeWidth = 8,
  size = 120,
  animated = false,
  autoIncrement = false,
  style,
  className,
}: ProgressProps) {
  const [displayValue, setDisplayValue] = useState(value)

  useEffect(() => {
    if (!animated) {
      setDisplayValue(value)
      return
    }
    const start = displayValue
    const end = value
    const duration = 400
    const startTime = performance.now()
    let raf: number
    const tick = (now: number) => {
      const t = Math.min(1, (now - startTime) / duration)
      setDisplayValue(start + (end - start) * t)
      if (t < 1) raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
    // displayValue is intentionally read only as the animation's starting
    // point; adding it would restart the animation on every animation frame.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value, animated])

  useEffect(() => {
    if (!autoIncrement) return
    const timer = setInterval(() => {
      setDisplayValue(v => (v >= 100 ? 0 : v + 1))
    }, 100)
    return () => clearInterval(timer)
  }, [autoIncrement])

  const percent = Math.min(100, Math.max(0, (displayValue / max) * 100))
  const color = colorMap[status]
  const text = format ? format(percent) : `${Math.round(percent)}%`

  if (type === 'circle') {
    const radius = (size - strokeWidth) / 2
    const circumference = 2 * Math.PI * radius
    const offset = circumference - (percent / 100) * circumference

    return (
      <div
        className={className}
        style={{
          display: 'inline-flex',
          alignItems: 'center',
          justifyContent: 'center',
          position: 'relative',
          width: size,
          height: size,
          ...style,
        }}
      >
        <svg width={size} height={size} style={{ transform: 'rotate(-90deg)' }}>
          <circle
            cx={size / 2}
            cy={size / 2}
            r={radius}
            fill="none"
            stroke="var(--bg-elevated)"
            strokeWidth={strokeWidth}
          />
          <circle
            cx={size / 2}
            cy={size / 2}
            r={radius}
            fill="none"
            stroke={color}
            strokeWidth={strokeWidth}
            strokeDasharray={circumference}
            strokeDashoffset={offset}
            strokeLinecap="round"
            style={{ transition: animated ? 'stroke-dashoffset 0.3s ease' : undefined }}
          />
        </svg>
        {showText && (
          <div style={{
            position: 'absolute',
            inset: 0,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            fontSize: size * 0.2,
            fontWeight: 600,
            color: 'var(--text-primary)',
          }}>
            {text}
          </div>
        )}
      </div>
    )
  }

  return (
    <div
      className={className}
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 10,
        ...style,
      }}
    >
      <div
        style={{
          flex: 1,
          height: strokeWidth,
          background: 'var(--bg-elevated)',
          borderRadius: strokeWidth / 2,
          overflow: 'hidden',
        }}
      >
        <div
          style={{
            width: `${percent}%`,
            height: '100%',
            background: color,
            borderRadius: strokeWidth / 2,
            transition: animated ? 'width 0.3s ease' : undefined,
            backgroundImage: status === 'normal' && animated
              ? 'linear-gradient(45deg, rgba(255,255,255,0.15) 25%, transparent 25%, transparent 50%, rgba(255,255,255,0.15) 50%, rgba(255,255,255,0.15) 75%, transparent 75%, transparent)'
              : undefined,
            backgroundSize: '20px 20px',
            animation: animated ? 'progress-stripe 1s linear infinite' : undefined,
          }}
        />
      </div>
      {showText && (
        <span style={{
          fontSize: Math.max(11, strokeWidth + 4),
          color: 'var(--text-secondary)',
          fontWeight: 500,
          minWidth: 36,
          textAlign: 'right',
        }}>
          {text}
        </span>
      )}
    </div>
  )
}


