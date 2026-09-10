export interface DividerProps {
  orientation?: 'horizontal' | 'vertical'
  style?: React.CSSProperties
  className?: string
}

/**
 * Divider 分隔线组件。
 *
 * 替代散落在各处的 `<div style={{ borderTop:... }}>` 重复代码。
 */
export default function Divider({
  orientation = 'horizontal',
  style,
  className,
}: DividerProps) {
  const isHorizontal = orientation === 'horizontal'

  return (
    <div
      className={className}
      style={{
        border: 'none',
        margin: 0,
        flexShrink: 0,
        ...(isHorizontal
          ? { borderTop: '1px solid var(--border)', width: '100%', height: 0 }
          : { borderLeft: '1px solid var(--border)', width: 0, height: '100%' }
        ),
        ...style,
      }}
    />
  )
}
