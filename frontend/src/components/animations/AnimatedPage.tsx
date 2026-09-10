import type { ReactNode } from 'react'

interface Props {
  children: ReactNode
}

export default function AnimatedPage({ children }: Props) {
  return (
    <div
      style={{ display: 'flex', flexDirection: 'column', flex: 1, overflow: 'auto', minHeight: 0 }}
    >
      {children}
    </div>
  )
}
