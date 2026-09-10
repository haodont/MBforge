import { useState, type ReactNode } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { fadeIn } from '../../hooks/useAnimations'

interface TooltipProps {
  /** 旧 API：纯文本。保留向下兼容。 */
  text?: string
  /** 新 API：可放任意 JSX（如两行布局）。优先于 text。 */
  content?: ReactNode
  children: ReactNode
  /** 显示在子元素的哪一侧 */
  position?: 'right' | 'left' | 'top' | 'bottom'
  /** 触发方式 */
  trigger?: 'hover' | 'click'
}

/**
 * Tooltip 气泡提示。
 *
 * 视觉与定位样式由 styles/ui.css 的 .ui-tooltip 类族承载。
 */
export default function Tooltip({
  text,
  content,
  children,
  position = 'right',
  trigger = 'hover',
}: TooltipProps) {
  const [show, setShow] = useState(false)
  const isRich = content !== undefined

  const eventHandlers = trigger === 'hover'
    ? { onMouseEnter: () => setShow(true), onMouseLeave: () => setShow(false) }
    : { onClick: () => setShow(!show), onMouseLeave: () => setShow(false) }

  const cls = ['ui-tooltip', `ui-tooltip--${position}`, isRich && 'ui-tooltip--rich']
    .filter(Boolean)
    .join(' ')

  return (
    <div className="ui-tooltip-host" {...eventHandlers}>
      {children}
      <AnimatePresence>
        {show && (
          <motion.div
            className={cls}
            variants={fadeIn}
            initial="hidden"
            animate="visible"
            exit="hidden"
          >
            {content ?? text}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}
