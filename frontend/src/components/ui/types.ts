/**
 * UI 组件 Props 类型统一导出。
 *
 * 让消费方可以从一个入口导入所有类型，无需了解内部模块结构。
 *
 * 使用方式:
 *   import type { ButtonProps, CardProps } from '@/components/ui/types'
 *   function MyComponent({ ...props }: ButtonProps) { ... }
 */

// ============ 枚举类（union types） ============
export type { ButtonVariant, ButtonSize } from './Button'
export type { BadgeVariant } from './Badge'
export type { AlertVariant } from './AlertBanner'

// ============ 组件 Props 类型 ============
export type { ButtonProps } from './Button'
export type { InputProps } from './Input'
export type { TextAreaProps } from './TextArea'
export type { CardProps } from './Card'
export type { CardGridProps } from './CardGrid'
export type { ModalProps } from './Modal'

// 设置相关
export type { SettingSectionProps } from './SettingSection'
export type { ResponsiveLayoutProps, ShowOnProps, HideOnProps, ResponsiveGridProps } from './ResponsiveContainer'
export type { ResponsiveStatGridProps } from './ResponsiveStatGrid'

// Icons
export type { IconProps } from '../icons/types'
