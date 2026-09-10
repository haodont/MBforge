/**
 * CSS 自定义属性（CSS variables）类型扩展。
 *
 * React.CSSProperties 在 @types/react 19.x 中不识别 `--foo` 形式的键，
 * 导致所有用到 CSS 变量的内联 style 都需要 `as React.CSSProperties` 断言。
 * 而该断言会把所有未知键（包括 `&:first-child` 这种非法选择器）一并放行，
 * 正是上一轮 Chat.tsx 那个 bug 能溜进来的根因。
 *
 * 这里通过模块声明合并，给 CSSProperties 加上一个 `--*` 的索引签名，
 * 之后：
 *   1. CSS 变量用法不再需要断言
 *   2. 任何非 CSS 变量、非合法 CSS 属性的键（特别是 `&:xxx`）会立刻被 TS 报错
 *
 * 参考：https://github.com/DefinitelyTyped/DefinitelyTyped/issues/30051
 */
import 'react'

declare module 'react' {
  interface CSSProperties {
    [key: `--${string}`]: string | number | undefined
  }
}

export {}
