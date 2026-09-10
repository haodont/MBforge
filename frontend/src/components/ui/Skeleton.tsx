import { motion } from 'framer-motion'

export interface SkeletonProps {
  variant?: 'card' | 'row' | 'text'
  count?: number
  height?: number
  style?: React.CSSProperties
  className?: string
}

export default function Skeleton({ variant = 'text', count = 1, height, style, className }: SkeletonProps) {
  const items = Array.from({ length: count }, (_, i) => i)

  const baseStyle: React.CSSProperties =
    variant === 'card'
      ? { height: height || 140, borderRadius: '12px', border: '1px solid var(--border)' }
      : variant === 'row'
      ? { height: height || 48, borderRadius: '8px', border: '1px solid var(--border)' }
      : { height: height || 16, borderRadius: '4px' }

  return (
    <>
      {items.map((i) => (
        <motion.div
          key={i}
          className={className}
          style={{
            background: 'var(--bg-surface)',
            ...baseStyle,
            ...style,
          }}
          animate={{ opacity: [0.4, 0.8, 0.4] }}
          transition={{ duration: 1.5, repeat: Infinity, delay: i * 0.1 }}
        />
      ))}
    </>
  )
}
