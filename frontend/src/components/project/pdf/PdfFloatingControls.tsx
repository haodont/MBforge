import { useTranslation } from 'react-i18next'
import type { MouseEvent } from 'react'
import Button from '@/components/ui/Button'
import IconButton from '@/components/ui/IconButton'
import Input from '@/components/ui/Input'
import { ChevronLeftIcon, ChevronRightIcon } from '@/components/icons'

interface Props {
  pdfScale: number
  onZoomIn: () => void
  onZoomOut: () => void
  onZoomReset: () => void
  currentPage: number
  pdfPageCount: number
  pageJumpInput: string
  onPageJumpInputChange: (v: string) => void
  onJumpToPage: () => void
  onPrevPage: () => void
  onNextPage: () => void
  continuousMode: boolean
  onToggleContinuous: () => void
}

export default function PdfFloatingControls(props: Props) {
  const { t } = useTranslation()
  const {
    pdfScale, onZoomIn, onZoomOut, onZoomReset,
    currentPage, pdfPageCount, pageJumpInput, onPageJumpInputChange, onJumpToPage,
    onPrevPage, onNextPage, continuousMode, onToggleContinuous,
  } = props

  // 浮层按钮点击后会抢焦点；不交还焦点会阻断主滚动容器的 wheel 翻页/滚动。
  // 统一在 click 之后 blur，让主滚动容器重新接收滚轮事件。
  const handleControlClick = (event: MouseEvent<HTMLButtonElement>, action: () => void) => {
    event.stopPropagation()
    action()
    const target = event.currentTarget
    requestAnimationFrame(() => {
      target.blur()
    })
  }

  // IconButton/Button 只转发 onClick 与 onMouseDown;这里统一包 blur 逻辑。
  const control = (
    title: string,
    ariaLabel: string,
    disabled: boolean | undefined,
    action: () => void,
    children: React.ReactNode,
    className?: string,
  ) => (
    <IconButton
      size={30}
      title={title}
      ariaLabel={ariaLabel}
      disabled={disabled}
      className={className}
      onMouseDown={(event) => event.preventDefault()}
      onClick={(event) => handleControlClick(event, action)}
    >
      {children}
    </IconButton>
  )

  return (
    <div className="pdf-floating-bar" onMouseDown={(event) => event.stopPropagation()}>
      {control(t('pdfFloat.prevPage'), t('pdfFloat.prevPage'), currentPage <= 1, onPrevPage, <ChevronLeftIcon size={14} />, 'pdf-floating-btn')}

      <div className="pdf-floating-page">
        <Input
          type="text"
          value={pageJumpInput || String(currentPage)}
          onChange={(e) => onPageJumpInputChange(e.target.value.replace(/\D/g, ''))}
          onKeyDown={(e) => { if (e.key === 'Enter') onJumpToPage() }}
          onBlur={() => onPageJumpInputChange('')}
          className="pdf-floating-page-input"
        />
        <span className="pdf-floating-page-sep">/</span>
        <span className="pdf-floating-page-total">{pdfPageCount || '?'}</span>
      </div>

      {control(t('pdfFloat.nextPage'), t('pdfFloat.nextPage'), currentPage >= (pdfPageCount || 1), onNextPage, <ChevronRightIcon size={14} />, 'pdf-floating-btn')}

      <div className="pdf-floating-divider" />

      {control(t('pdfFloat.zoomOut'), t('pdfFloat.zoomOut'), undefined, onZoomOut, (
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M5 12h14" />
        </svg>
      ), 'pdf-floating-btn')}

      <Button
        size="sm"
        variant="ghost"
        title={t('pdfFloat.zoomReset')}
        className="pdf-floating-zoom"
        onMouseDown={(event) => event.preventDefault()}
        onClick={(event) => handleControlClick(event, onZoomReset)}
      >
        {Math.round(pdfScale * 100)}%
      </Button>

      {control(t('pdfFloat.zoomIn'), t('pdfFloat.zoomIn'), undefined, onZoomIn, (
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M12 5v14M5 12h14" />
        </svg>
      ), 'pdf-floating-btn')}

      <Button
        size="sm"
        variant="ghost"
        className={`pdf-floating-mode ${continuousMode ? 'is-active' : ''}`}
        title={continuousMode ? t('pdfFloat.singlePage') : t('pdfFloat.continuous')}
        ariaLabel={continuousMode ? t('pdfFloat.singlePage') : t('pdfFloat.continuous')}
        onMouseDown={(event) => event.preventDefault()}
        onClick={(event) => handleControlClick(event, onToggleContinuous)}
      >
        ⋮
      </Button>
    </div>
  )
}
