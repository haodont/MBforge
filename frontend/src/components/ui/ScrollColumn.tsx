// ScrollColumn — flex column 内的垂直滚动容器。
//
// 把 "flex: 1 + min-height: 0 + overflow-y: auto" 三件套封装到一处。
//
// 为什么需要：在 flex column 父容器里，flex child 默认 min-height: auto，
// 至少和 content 一样高。**只**写 overflow-y: auto 而不写 min-height: 0，
// scroll 永远不会触发：child 直接撑破父容器，整页变成一个无止境的长条。
//
// 经典踩坑现场（同一根因，反复出现）：
//   - SettingsModal 右内容滚动区（被报告为"Environment 页面不能滚动"）
//   - App.tsx main flex container
//   - ErrorBoundary children wrapper
//
// 用 ScrollColumn 替代手写 div style，让这三件套不可能被漏写。
// padding 是个糖，等价于 style={{ padding }}。

import { forwardRef, type CSSProperties, type ReactNode } from 'react'

export interface ScrollColumnProps extends React.HTMLAttributes<HTMLDivElement> {
  children: ReactNode
  /** 透传 className */
  className?: string
  /**
   * 透传额外 style。最后合并，**可以覆盖** flex / min-height / overflow-y
   * 任意字段，但 99% 的用例应该让 ScrollColumn 替你管这三件套。
   */
  style?: CSSProperties
  /** 简写：等价于 style={{ padding }} */
  padding?: string | number
  /**
   * as 渲染的元素类型。默认 div，需要 section / main / aside / article /
   * nav 等语义元素时改这里。
   */
  as?: 'div' | 'section' | 'main' | 'aside' | 'article' | 'nav'
}

const ScrollColumn = forwardRef<HTMLDivElement, ScrollColumnProps>(
  function ScrollColumn({ children, className, style, padding, as: Tag = 'div', ...rest }, ref) {
    return (
      <Tag
        ref={ref}
        className={className}
        style={{
          flex: 1,
          minHeight: 0,
          overflowY: 'auto',
          padding,
          ...style,
        }}
        {...rest}
      >
        {children}
      </Tag>
    )
  }
)

export default ScrollColumn
