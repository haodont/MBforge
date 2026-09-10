export type StepStatus = 'normal' | 'success' | 'error' | 'warning'
export type StepDirection = 'horizontal' | 'vertical'
export type StepSize = 'sm' | 'md' | 'lg'

export interface StepItem {
  title: string
  description?: string
}

export interface StepsProps {
  current: number
  steps: StepItem[]
  direction?: StepDirection
  size?: StepSize
  style?: React.CSSProperties
}

/**
 * Steps 步骤进度条。
 *
 * 显示多步骤流程的当前进度，支持横向和纵向布局。
 */
export default function Steps({
  current,
  steps,
  direction = 'horizontal',
  size = 'md',
  style,
}: StepsProps) {
  const dotSize = { sm: 24, md: 32, lg: 40 }[size]
  const fontSize = { sm: 11, md: 13, lg: 14 }[size]
  const isHorizontal = direction === 'horizontal'

  return (
    <div style={{
      display: 'flex',
      flexDirection: isHorizontal ? 'row' : 'column',
      gap: isHorizontal ? 0 : 16,
      alignItems: isHorizontal ? 'flex-start' : 'stretch',
      ...style,
    }}>
      {steps.map((step, i) => {
        const isDone = i < current
        const isCurrent = i === current
        const bg = isDone || isCurrent ? 'var(--accent)' : 'var(--bg-elevated)'

        return (
          <div
            key={i}
            style={{
              display: 'flex',
              flexDirection: direction === 'horizontal' ? 'column' : 'row',
              alignItems: 'center',
              gap: direction === 'horizontal' ? 8 : 16,
              flex: direction === 'horizontal' ? 1 : undefined,
              position: 'relative',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', flex: 1 }}>
              {i > 0 && direction === 'horizontal' && (
                <div style={{
                  flex: 1,
                  height: 2,
                  background: isDone ? 'var(--accent)' : 'var(--bg-elevated)',
                  marginRight: 8,
                }} />
              )}
              <div style={{
                width: dotSize,
                height: dotSize,
                borderRadius: '50%',
                background: bg,
                color: isDone || isCurrent ? 'white' : 'var(--text-muted)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                fontSize: fontSize,
                fontWeight: 600,
                flexShrink: 0,
                boxShadow: isCurrent ? '0 0 0 4px var(--accent-muted)' : undefined,
              }}>
                {isDone ? '✓' : i + 1}
              </div>
              {direction === 'horizontal' && i < steps.length - 1 && (
                <div style={{
                  flex: 1,
                  height: 2,
                  background: i < current ? 'var(--accent)' : 'var(--bg-elevated)',
                  marginLeft: 8,
                }} />
              )}
            </div>
            <div style={{
              textAlign: direction === 'horizontal' ? 'center' : 'left',
              flex: direction === 'vertical' ? 1 : undefined,
            }}>
              <div style={{
                fontSize: fontSize,
                fontWeight: isCurrent ? 600 : 500,
                color: isDone || isCurrent ? 'var(--text-primary)' : 'var(--text-muted)',
              }}>
                {step.title}
              </div>
              {step.description && (
                <div style={{
                  fontSize: fontSize - 1,
                  color: 'var(--text-muted)',
                  marginTop: 2,
                }}>
                  {step.description}
                </div>
              )}
            </div>
          </div>
        )
      })}
    </div>
  )
}
