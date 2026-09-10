/**
 * 通用样式模式 / 模式组合。
 *
 * 目的：消除散落的内联样式重复，提升代码可读性。
 *
 * 使用方式:
 *   import { PATTERNS, SIZES } from '@/styles/patterns'
 *   <div style={{ ...PATTERNS.surfaceBlock, padding: SIZES.padding.md }} />
 */

import type { CSSProperties } from 'react'

// ============================================================================
// 间距 / 圆角 / 尺寸常量
// ============================================================================

export const SIZES = {
  padding: {
    sm: 8,
    md: 12,
    lg: 16,
    xl: 20,
  },
  radius: {
    sm: 6,
    md: 8,
    lg: 12,
    xl: 16,
  },
  fontSize: {
    xs: '11px',
    sm: '12px',
    base: '13px',
    md: '14px',
    lg: '16px',
    xl: '20px',
  },
} as const

// ============================================================================
// 通用样式模式
// ============================================================================

/** 表面块：背景 + 边框 + 圆角（最常用的容器） */
export const surfaceBlock: CSSProperties = {
  background: 'var(--bg-surface)',
  border: '1px solid var(--border)',
  borderRadius: 'var(--radius-card)',
  padding: 'var(--space-4)',
  boxShadow: 'var(--shadow-sm)',
}

/** 表面块（无 padding，由调用方决定） */
export const surfaceBlockNoPadding: CSSProperties = {
  background: 'var(--bg-surface)',
  border: '1px solid var(--border)',
  borderRadius: 'var(--radius-card)',
}

/** 表面块（强调边框） */
export const surfaceBlockAccent: CSSProperties = {
  background: 'var(--bg-base)',
  border: '1px solid var(--accent)',
  borderRadius: SIZES.radius.xl,
}

/** 行内块：圆角小 + 浅背景（用于 chip / 标签） */
export const chip: CSSProperties = {
  padding: `2px 8px`,
  borderRadius: SIZES.radius.sm,
  fontSize: SIZES.fontSize.base,
  fontWeight: 500,
}

/** 居中容器 */
export const centerContainer: CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'center',
}

/** 横向弹性容器（默认 8px gap） */
export const hstack = (gap: number | string = 8): CSSProperties => ({
  display: 'flex',
  alignItems: 'center',
  gap,
})

/** 纵向弹性容器（默认 8px gap） */
export const vstack = (gap: number | string = 8): CSSProperties => ({
  display: 'flex',
  flexDirection: 'column',
  gap,
})

/** 全屏遮罩 */
export const fullscreenBackdrop: CSSProperties = {
  position: 'fixed',
  inset: 0,
  zIndex: 1000,
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'center',
}

/** 模态框面板 */
export const modalPanel: CSSProperties = {
  position: 'relative',
  background: 'var(--bg-surface)',
  borderRadius: SIZES.radius.xl,
  border: '1px solid var(--border)',
  boxShadow: 'var(--shadow-lg)',
  display: 'flex',
  flexDirection: 'column',
  overflow: 'hidden',
}

/** 标准设置行：固定 label 宽度，control 区自适应 */
export const settingRow: CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  gap: 'var(--space-4)',
}

export const settingLabel = (width = 160): CSSProperties => ({
  width,
  flexShrink: 0,
})

export const settingControl: CSSProperties = {
  flex: 1,
  minWidth: 280,
  maxWidth: 480,
}

/** 所有 patterns 集合（便于一次性导入） */
export const PATTERNS = {
  surfaceBlock,
  surfaceBlockNoPadding,
  surfaceBlockAccent,
  chip,
  centerContainer,
  fullscreenBackdrop,
  modalPanel,
  settingRow,
  settingLabel,
  settingControl,
} as const
