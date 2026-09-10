/**
 * framer-motion 动画预定义变体
 * 
 * 集中管理所有动画参数，确保跨组件一致性。
 * 
 * 使用方式:
 *   import { fadeUp, fadeIn } from '@/hooks/useAnimations'
 *   <motion.div variants={fadeUp} initial="hidden" animate="visible">
 */

import { Variants } from 'framer-motion'

// ============================================================================
// 基础动画变体
// ============================================================================

/** 淡入 + 轻微上移（默认 300ms）— 最常用的入场动画 */
export const fadeUp: Variants = {
  hidden: { opacity: 0, y: 10 },
  visible: { 
    opacity: 1, 
    y: 0, 
    transition: { duration: 0.3 } 
  },
}

/** 纯淡入（默认 200ms）— 快速淡入 */
export const fadeIn: Variants = {
  hidden: { opacity: 0 },
  visible: { 
    opacity: 1, 
    transition: { duration: 0.2 } 
  },
}

/** 淡入 + 轻微放大（默认 250ms）— 弹入效果 */
export const scaleIn: Variants = {
  hidden: { opacity: 0, scale: 0.96 },
  visible: { 
    opacity: 1, 
    scale: 1, 
    transition: { duration: 0.25, ease: 'easeOut' } 
  },
}

/** 缩放弹入（用于按钮等可点击元素） */
export const scaleInBounce: Variants = {
  hidden: { opacity: 0, scale: 0.8 },
  visible: { 
    opacity: 1, 
    scale: 1, 
    transition: { 
      duration: 0.25, 
      ease: 'easeOut' 
    } 
  },
}

// ============================================================================
// 页面切换动画
// ============================================================================

/** 从右侧滑入 — 页面/面板切换 */
export const slideFromRight: Variants = {
  hidden: { opacity: 0, x: 20 },
  visible: { 
    opacity: 1, 
    x: 0, 
    transition: { duration: 0.25 } 
  },
  exit: { 
    opacity: 0, 
    x: -20, 
    transition: { duration: 0.25 } 
  },
}

/** 从左侧滑入 — 页面/面板切换 */
export const slideFromLeft: Variants = {
  hidden: { opacity: 0, x: -20 },
  visible: { 
    opacity: 1, 
    x: 0, 
    transition: { duration: 0.25 } 
  },
  exit: { 
    opacity: 0, 
    x: 20, 
    transition: { duration: 0.25 } 
  },
}

/** 从底部滑入 — 模态框/下拉 */
export const slideFromBottom: Variants = {
  hidden: { opacity: 0, y: 20 },
  visible: { 
    opacity: 1, 
    y: 0, 
    transition: { duration: 0.25 } 
  },
  exit: { 
    opacity: 0, 
    y: 20, 
    transition: { duration: 0.2 } 
  },
}

// ============================================================================
// 交错容器
// ============================================================================

/** 默认交错容器配置 */
export const staggerContainer: Variants = {
  hidden: { opacity: 0 },
  visible: {
    opacity: 1,
    transition: { 
      staggerChildren: 0.06, 
      delayChildren: 0 
    },
  },
}

/** 慢速交错容器（stagger: 0.1s） */
export const staggerContainerSlow: Variants = {
  hidden: { opacity: 0 },
  visible: {
    opacity: 1,
    transition: { 
      staggerChildren: 0.1, 
      delayChildren: 0 
    },
  },
}

/** 快速交错容器（stagger: 0.04s） */
export const staggerContainerFast: Variants = {
  hidden: { opacity: 0 },
  visible: {
    opacity: 1,
    transition: { 
      staggerChildren: 0.04, 
      delayChildren: 0 
    },
  },
}

/** 交错子项默认配置（配合 staggerContainer 使用） */
export const staggerItem: Variants = {
  hidden: { opacity: 0, y: 10 },
  show: { 
    opacity: 1, 
    y: 0, 
    transition: { duration: 0.3 } 
  },
}

/** 交错子项：仅淡入 */
export const staggerItemFadeOnly: Variants = {
  hidden: { opacity: 0 },
  show: { 
    opacity: 1, 
    transition: { duration: 0.2 } 
  },
}

// ============================================================================
// 悬停动画
// ============================================================================

/** 悬停时轻微放大 */
export const hoverScale = {
  scale: 1.02,
  transition: { duration: 0.15 },
}

/** 悬停时轻微上移 */
export const hoverLift = {
  y: -2,
  transition: { duration: 0.15 },
}

/** 悬停时边框高亮 */
export const hoverBorderHighlight = {
  borderColor: 'var(--accent)',
  transition: { duration: 0.15 },
}

// ============================================================================
// 悬停/点击动效
// ============================================================================

/** 点击时轻微缩小 */
export const tapScale = {
  scale: 0.8,
  transition: { duration: 0.15 },
}

/** Logo 入场动画：缩放 + 淡入 */
export const logoEntrance: Variants = {
  hidden: { scale: 0.8, opacity: 0 },
  visible: { 
    scale: 1, 
    opacity: 1, 
    transition: { duration: 0.5, ease: 'easeOut' } 
  },
}

/** 模态框入场：缩放 + 淡入 + 上移 */
export const modalEntrance: Variants = {
  hidden: { opacity: 0, scale: 0.96, y: 8 },
  visible: { 
    opacity: 1, 
    scale: 1, 
    y: 0, 
    transition: { duration: 0.25, ease: 'easeOut' } 
  },
  exit: { 
    opacity: 0, 
    scale: 0.96, 
    y: 8, 
    transition: { duration: 0.2 } 
  },
}

/** 项目卡片悬停效果 */
export const projectCardHover = {
  borderColor: 'var(--accent)',
  x: 2,
  transition: { duration: 0.15 },
}

// ============================================================================
// 组合便捷函数
// ============================================================================

/**
 * 创建带延迟的 fadeUp 变体
 * 
 * @param delay - 延迟秒数
 * @param duration - 动画持续秒数，默认 0.3
 */
export function fadeUpWithDelay(delay: number, duration = 0.3): Variants {
  return {
    hidden: { opacity: 0, y: 10 },
    visible: { 
      opacity: 1, 
      y: 0, 
      transition: { duration, delay } 
    },
  }
}

/**
 * 创建带延迟的 fadeIn 变体
 * 
 * @param delay - 延迟秒数
 * @param duration - 动画持续秒数，默认 0.2
 */
export function fadeInWithDelay(delay: number, duration = 0.2): Variants {
  return {
    hidden: { opacity: 0 },
    visible: { 
      opacity: 1, 
      transition: { duration, delay } 
    },
  }
}

/**
 * 创建自定义 stagger 配置
 * 
 * @param stagger - 子项间隔，默认 0.06
 * @param delay - 容器延迟，默认 0
 */
export function makeStaggerContainer(stagger = 0.06, delay = 0): Variants {
  return {
    hidden: { opacity: 0 },
    visible: {
      opacity: 1,
      transition: { staggerChildren: stagger, delayChildren: delay },
    },
  }
}
