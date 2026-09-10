import type { ReactNode } from 'react'
import Button from './Button'
import Modal from './Modal'

export interface ConfirmDialogProps {
  open: boolean
  /** 标题（如"删除文档"）*/
  title: string
  /** 说明正文，支持节点 */
  message?: ReactNode
  confirmLabel?: string
  cancelLabel?: string
  /** 确认按钮是否用危险色（默认 true）*/
  danger?: boolean
  /** 确认动作进行中：按钮 loading 并防重复提交 */
  loading?: boolean
  onConfirm: () => void | Promise<void>
  onCancel: () => void
}

/**
 * ConfirmDialog 统一确认弹窗。
 *
 * 基于 ui/Modal + Button 的破坏性/重要操作确认，替代各处 window.confirm。
 * 视觉样式由 styles/ui.css 的 .ui-modal / .ui-btn 类族承载。
 */
export default function ConfirmDialog({
  open,
  title,
  message,
  confirmLabel = '确认',
  cancelLabel = '取消',
  danger = true,
  loading = false,
  onConfirm,
  onCancel,
}: ConfirmDialogProps) {
  return (
    <Modal
      open={open}
      onClose={onCancel}
      title={title}
      width={420}
      maxWidth={420}
      height="auto"
      maxHeight={360}
      footer={
        <>
          <Button variant="ghost" onClick={onCancel} disabled={loading}>{cancelLabel}</Button>
          <Button variant={danger ? 'danger' : 'primary'} onClick={() => void onConfirm()} loading={loading}>{confirmLabel}</Button>
        </>
      }
    >
      {message && (
        <div style={{ color: 'var(--text-secondary)', fontSize: 13, lineHeight: '20px' }}>{message}</div>
      )}
    </Modal>
  )
}
