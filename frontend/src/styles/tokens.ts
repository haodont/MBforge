/**
 * 集中管理所有 UI 颜色、状态色、语义色 token。
 *
 * 目的：消除散落在多个组件中的颜色硬编码，确保视觉一致性。
 *
 * 使用方式:
 *   import { STATUS_COLORS, ALPHA } from '@/styles/tokens'
 *   <Badge style={{ background: ALPHA.success[10] }} />
 */

// ============================================================================
// 基础色板（raw palette）
// ============================================================================

/**
 * 与 styles/theme.css 的浅色主题令牌保持一致 —— 改色请先改 theme.css。
 * 注意：内联样式无法随主题切换，新组件应优先使用 CSS 变量而非本表。
 */
export const PALETTE = {
  success: '#16a34a',
  warning: '#d97706',
  danger:  '#dc2626',
  error:   '#dc2626',
  info:    '#2563eb',
  neutral: '#545963',
  muted:   '#767c88',
} as const

// ============================================================================
// 透明度叠加（alpha tint）
// ============================================================================

/**
 * 16 进制颜色 → rgba 字符串
 * @param hex 形如 "#16a34a"
 * @param alpha 0-1
 */
export function withAlpha(hex: string, alpha: number): string {
  const r = parseInt(hex.slice(1, 3), 16)
  const g = parseInt(hex.slice(3, 5), 16)
  const b = parseInt(hex.slice(5, 7), 16)
  return `rgba(${r}, ${g}, ${b}, ${alpha})`
}

/** 预计算各状态色的常用透明度叠加 */
export const ALPHA = {
  success: {
    10: withAlpha(PALETTE.success, 0.1),
    30: withAlpha(PALETTE.success, 0.3),
  },
  warning: {
    10: withAlpha(PALETTE.warning, 0.1),
    30: withAlpha(PALETTE.warning, 0.3),
  },
  danger: {
    10: withAlpha(PALETTE.danger, 0.1),
    30: withAlpha(PALETTE.danger, 0.3),
  },
  error: {
    10: withAlpha(PALETTE.error, 0.1),
    30: withAlpha(PALETTE.error, 0.3),
  },
  info: {
    10: withAlpha(PALETTE.info, 0.1),
    30: withAlpha(PALETTE.info, 0.3),
  },
} as const

// ============================================================================
// Variant 配置映射
// ============================================================================

export type StatusTone = 'success' | 'warning' | 'danger' | 'error' | 'info' | 'neutral'

/** 通用 status tone 配色方案（用于 Badge、Alert、Toast 等） */
export const TONE_COLORS: Record<StatusTone, { color: string; bg: string; border: string }> = {
  success: { color: PALETTE.success, bg: ALPHA.success[10], border: ALPHA.success[30] },
  warning: { color: PALETTE.warning, bg: ALPHA.warning[10], border: ALPHA.warning[30] },
  danger:  { color: PALETTE.danger,  bg: ALPHA.danger[10],  border: ALPHA.danger[30]  },
  error:   { color: PALETTE.error,   bg: ALPHA.error[10],   border: ALPHA.error[30]   },
  info:    { color: PALETTE.info,    bg: ALPHA.info[10],    border: ALPHA.info[30]    },
  neutral: { color: PALETTE.neutral, bg: '#eff0f4',         border: '#d3d5dc'         },
}
