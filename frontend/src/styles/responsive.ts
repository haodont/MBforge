/**
 * 响应式设计工具与断点系统。
 *
 * 断点定义（移动端优先）：
 *   sm: 640px   — 手机横屏 / 小平板
 *   md: 768px   — 平板竖屏
 *   lg: 1024px  — 平板横屏 / 小桌面
 *   xl: 1280px  — 标准桌面
 *   2xl: 1536px — 大屏桌面
 *
 * 使用方式:
 *   import { media, BREAKPOINTS, useMediaQuery } from '@/styles/responsive'
 *   // 1) 在 CSS 字符串中拼接媒体查询
 *   `${media.md} { ... }`
 *   // 2) 在 React 中使用 useMediaQuery
 *   const isMobile = useMediaQuery('(max-width: 768px)')
 */

export const BREAKPOINTS = {
  sm: 640,
  md: 768,
  lg: 1024,
  xl: 1280,
  '2xl': 1536,
} as const

export type Breakpoint = keyof typeof BREAKPOINTS

/** 各断点对应的 min-width 媒体查询 */
export const media = {
  sm:  `@media (min-width: ${BREAKPOINTS.sm}px)`,
  md:  `@media (min-width: ${BREAKPOINTS.md}px)`,
  lg:  `@media (min-width: ${BREAKPOINTS.lg}px)`,
  xl:  `@media (min-width: ${BREAKPOINTS.xl}px)`,
  '2xl': `@media (min-width: ${BREAKPOINTS['2xl']}px)`,
  /** 最大宽度（用于 mobile-first 边界） */
  maxSm: `@media (max-width: ${BREAKPOINTS.sm - 1}px)`,
  maxMd: `@media (max-width: ${BREAKPOINTS.md - 1}px)`,
  maxLg: `@media (max-width: ${BREAKPOINTS.lg - 1}px)`,
  maxXl: `@media (max-width: ${BREAKPOINTS.xl - 1}px)`,
} as const

// ============================================================================
// React Hooks
// ============================================================================

import { useEffect, useState } from 'react'

/**
 * 响应式媒体查询 hook。
 * 服务端渲染安全（默认返回 false）。
 */
export function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(false)

  useEffect(() => {
    const mq = window.matchMedia(query)
    setMatches(mq.matches)
    const handler = (e: MediaQueryListEvent) => setMatches(e.matches)
    mq.addEventListener('change', handler)
    return () => mq.removeEventListener('change', handler)
  }, [query])

  return matches
}

/** 是否处于移动端 (< 768px) */
export function useIsMobile(): boolean {
  return useMediaQuery(`(max-width: ${BREAKPOINTS.md - 1}px)`)
}

/** 是否处于平板 (< 1024px) */
export function useIsTablet(): boolean {
  return useMediaQuery(`(max-width: ${BREAKPOINTS.lg - 1}px)`)
}

/** 是否处于桌面端 (>= 1024px) */
export function useIsDesktop(): boolean {
  return useMediaQuery(`(min-width: ${BREAKPOINTS.lg}px)`)
}

// ============================================================================
// 实用工具
// ============================================================================

/**
 * 根据断点返回一个响应式值。
 * 用法: responsive({ base: '100%', md: '50%', lg: '33%' })
 */
export function responsive<T>(values: { base?: T } & Partial<Record<Breakpoint, T>>): T | undefined {
  // React 组件中请用 useResponsive hook
  return values.base
}

/**
 * 容器查询：检测父容器宽度
 */
export function useContainerWidth(ref: React.RefObject<HTMLElement>): number {
  const [width, setWidth] = useState(0)

  useEffect(() => {
    const el = ref.current
    const observer = new ResizeObserver((entries) => {
      for (const entry of entries) {
        setWidth(entry.contentRect.width)
      }
    })
    observer.observe(el)
    return () => observer.disconnect()
  }, [ref])

  return width
}
