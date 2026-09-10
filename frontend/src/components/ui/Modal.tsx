import { motion, AnimatePresence } from 'framer-motion'
import type { ReactNode } from 'react'
import IconButton from './IconButton'
import ScrollColumn from './ScrollColumn'
import { XIcon } from '../icons'
import { useIsMobile } from '../../styles/responsive'

export interface ModalProps {
  open: boolean
  onClose: () => void
  title?: string
  children: ReactNode
  footer?: ReactNode
  width?: string | number
  maxWidth?: string | number
  height?: string | number
  maxHeight?: string | number
  /** 移动端是否全屏显示（默认 true） */
  fullScreenOnMobile?: boolean
}

/**
 * Modal 对话框。
 *
 * 静态视觉样式由 styles/ui.css 的 .ui-modal 类族承载；
 * 宽高、圆角等随 props/断点动态变化的值保留内联。
 */
export default function Modal({
  open,
  onClose,
  title,
  children,
  footer,
  width = '90%',
  maxWidth = 860,
  height = '80%',
  maxHeight = 640,
  fullScreenOnMobile = true,
}: ModalProps) {
  const isMobile = useIsMobile()

  // 移动端可选全屏显示
  const finalWidth = isMobile && fullScreenOnMobile ? '100%' : width
  const finalMaxWidth = isMobile && fullScreenOnMobile ? '100%' : maxWidth
  const finalHeight = isMobile && fullScreenOnMobile ? '100%' : height
  const finalMaxHeight = isMobile && fullScreenOnMobile ? '100%' : maxHeight
  const borderRadius = isMobile && fullScreenOnMobile ? 0 : 'var(--radius-panel)'

  return (
    <AnimatePresence>
      {open && (
        <motion.div
          className="ui-modal"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.2 }}
        >
          {/* Backdrop */}
          <motion.div
            className="ui-modal__backdrop"
            onClick={onClose}
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.2 }}
          />

          {/* Modal */}
          <motion.div
            className="ui-modal__panel"
            initial={{ opacity: 0, scale: 0.96, y: 8 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.96, y: 8 }}
            transition={{ duration: 0.25, ease: 'easeOut' }}
            style={{
              width: finalWidth,
              maxWidth: finalMaxWidth,
              height: finalHeight,
              maxHeight: finalMaxHeight,
              borderRadius,
            }}
          >
            {/* Header */}
            {title && (
              <div className="ui-modal__header">
                <h2 className="ui-modal__title">{title}</h2>
                <IconButton size={40} onClick={onClose} title="关闭">
                  <XIcon size={18} />
                </IconButton>
              </div>
            )}

            {/* Content */}
            <ScrollColumn padding="16px 20px">
              {children}
            </ScrollColumn>

            {/* Footer */}
            {footer && (
              <div className="ui-modal__footer">
                {footer}
              </div>
            )}
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  )
}
