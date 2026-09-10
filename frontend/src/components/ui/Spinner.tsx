export interface SpinnerProps {
  size?: number
  color?: string
  style?: React.CSSProperties
}

export default function Spinner({ size = 16, color = 'currentColor', style }: SpinnerProps) {
  return (
    <span
      style={{
        display: 'inline-block',
        width: size,
        height: size,
        border: `2px solid ${color === 'currentColor' ? 'currentColor' : color + '40'}`,
        borderTopColor: color,
        borderRadius: '50%',
        animation: 'spin 0.6s linear infinite',
        ...style,
      }}
    />
  )
}
