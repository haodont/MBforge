import { useEffect, useRef, useState } from 'react'
import { motion } from 'framer-motion'
import { CheckIcon, AlertIcon, InfoIcon } from '../icons'
import { basicValidate } from './moleculeUtils'
import { smilesToRdkitSvg } from '@/api/http/molecule'
import ConfidenceBadge from './ConfidenceBadge'
import { useMoleculeDisplay } from '@/hooks/useMoleculeDisplay'
import Button from '@/components/ui/Button'
import Input from '@/components/ui/Input'

export interface MoleculeDisplayProps {
  smiles: string
  mode?: 'view' | 'edit' | 'compare'
  name?: string
  size?: number
  background?: string
  showMetadata?: boolean
  confidence?: number
  source?: string
  /** Optional original crop used only when both structure renderers fail. */
  sourceImageUrl?: string
  /** Skip server-side validation for dense, read-only structure previews. */
  validateRemotely?: boolean
  onChange?: (newSmiles: string) => void
  onValidate?: (isValid: boolean, message?: string) => void
  className?: string
  style?: React.CSSProperties
}

export default function MoleculeDisplay({
  smiles,
  mode = 'view',
  name,
  size = 240,
  background = 'white',
  showMetadata = false,
  confidence,
  source,
  sourceImageUrl,
  validateRemotely = true,
  onChange,
  onValidate,
  className,
  style,
}: MoleculeDisplayProps) {
  const inputRef = useRef<HTMLInputElement>(null)
  const [renderSource, setRenderSource] = useState<'rdkit' | 'crop'>('rdkit')
  const [rdkitSvg, setRdkitSvg] = useState<string | null>(null)
  const [rdkitRenderError, setRdkitRenderError] = useState<string | null>(null)
  const [rdkitLoading, setRdkitLoading] = useState(false)
  const [renderAttempt, setRenderAttempt] = useState(0)
  const validation = basicValidate(smiles)

  const {
    imgError,
    setImgError,
    isEditing,
    draftSmiles,
    backendIssue,
    backendLoading,
    effectiveError,
    formula,
    mw,
    handleStartEdit,
    handleApplyEdit,
    handleCancelEdit,
    handleKeyDown,
    setDraftSmiles,
  } = useMoleculeDisplay(
    smiles,
    name,
    showMetadata,
    onChange,
    onValidate,
    validateRemotely,
  )

  useEffect(() => {
    setRenderSource('rdkit')
    setRdkitSvg(null)
    setRdkitRenderError(null)
    setRdkitLoading(false)
    setImgError(false)
  }, [setImgError, smiles])

  useEffect(() => {
    if (renderSource !== 'rdkit' || !validation.valid) {
      return
    }

    let cancelled = false
    setRdkitLoading(true)
    setRdkitSvg(null)
    setRdkitRenderError(null)
    smilesToRdkitSvg(smiles, size, size)
      .then((svg) => {
        if (!cancelled) setRdkitSvg(svg)
      })
      .catch((error: unknown) => {
        if (!cancelled && sourceImageUrl) setRenderSource('crop')
        if (!cancelled) {
          setRdkitRenderError(error instanceof Error ? error.message : '本地结构渲染失败')
        }
      })
      .finally(() => {
        if (!cancelled) setRdkitLoading(false)
      })

    return () => { cancelled = true }
  }, [renderAttempt, renderSource, size, smiles, sourceImageUrl, validation.valid])

  const retryStructureRender = (event: React.MouseEvent<HTMLButtonElement>) => {
    event.stopPropagation()
    setImgError(false)
    setRenderSource('rdkit')
    setRenderAttempt((attempt) => attempt + 1)
  }

  const handleStructureImageError = () => {
    if (renderSource === 'rdkit' && sourceImageUrl) {
      setRenderSource('crop')
      return
    }
    setImgError(true)
  }

  const startEdit = () => {
    handleStartEdit()
    setTimeout(() => inputRef.current?.focus(), 50)
  }

  return (
    <div
      className={`mol-display ${effectiveError ? 'mol-display--error' : ''} ${className ?? ''}`}
      style={style}
    >
      {(name || confidence !== undefined || source) && (
        <div className="mol-display-header">
          <div className="mol-display-meta">
            {name && (
              <div className="mol-display-name" title={name}>
                {name}
              </div>
            )}
            {source && (
              <div className="mol-display-source">来源：{source}</div>
            )}
          </div>
          {confidence !== undefined && <ConfidenceBadge value={confidence} />}
        </div>
      )}

      <div
        className="mol-display-canvas"
        style={{ background, minHeight: size }}
      >
        {isEditing ? (
          <div className="mol-edit-form">
            <Input
              ref={inputRef}
              type="text"
              value={draftSmiles}
              onChange={(e) => setDraftSmiles(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="输入 SMILES..."
              ariaLabel="SMILES"
              error={!!effectiveError}
              className="mol-edit-input"
            />
            {effectiveError && (
              <div className="mol-edit-error">
                <AlertIcon size={12} /> {effectiveError}
                {backendLoading && <span className="mol-edit-error-hint">（校验中…）</span>}
              </div>
            )}
            <div className="mol-edit-actions">
              <Button
                variant="primary"
                size="sm"
                icon={<CheckIcon size={12} />}
                className="mol-edit-btn"
                onClick={(event) => {
                  event.stopPropagation()
                  handleApplyEdit()
                }}
              >
                应用
              </Button>
              <Button
                variant="secondary"
                size="sm"
                className="mol-edit-btn"
                onClick={(event) => {
                  event.stopPropagation()
                  handleCancelEdit()
                }}
              >
                取消
              </Button>
            </div>
          </div>
        ) : imgError ? (
          <div className="mol-display-placeholder">
            <div className="mol-display-placeholder-icon">
              <svg width={48} height={48} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.5} strokeLinecap="round" strokeLinejoin="round">
                <rect x="2" y="2" width="20" height="20" rx="3" />
                <circle cx="8.5" cy="8.5" r="1.5" />
                <path d="m21 15-5-5L5 21" />
              </svg>
            </div>
            <div className="mol-display-placeholder-title">网络不可用</div>
            <div className="mol-display-placeholder-hint">
              {validation.valid ? '无法加载分子结构图，请检查网络连接' : (validation.message ?? '无法渲染此 SMILES')}
            </div>
            <Button
              size="sm"
              variant="ghost"
              className="mol-display-placeholder-btn"
              onClick={retryStructureRender}
            >
              重试
            </Button>
          </div>
        ) : !validation.valid ? (
          <div className="mol-display-placeholder">
            <InfoIcon size={32} />
            <div className="mol-display-placeholder-title">{validation.message}</div>
          </div>
        ) : renderSource === 'rdkit' && rdkitRenderError ? (
          <div className="mol-display-placeholder mol-display-placeholder--error">
            <AlertIcon size={32} />
            <div className="mol-display-placeholder-title">本地结构渲染失败</div>
            <div className="mol-display-placeholder-hint">{rdkitRenderError}</div>
          </div>
        ) : renderSource === 'rdkit' && (rdkitLoading || !rdkitSvg) ? (
          <div className="mol-display-placeholder">
            <InfoIcon size={32} />
            <div className="mol-display-placeholder-title">正在渲染本地结构图</div>
          </div>
        ) : backendIssue && backendIssue.severity === 'error' && !backendLoading ? (
          <div className="mol-display-placeholder mol-display-placeholder--error">
            <AlertIcon size={32} />
            <div className="mol-display-placeholder-title">化学结构无效</div>
            <div className="mol-display-placeholder-hint">{backendIssue.message}</div>
          </div>
        ) : (
          <>
            <motion.img
              key={smiles}
              src={renderSource === 'rdkit' && rdkitSvg
                ? `data:image/svg+xml;charset=utf-8,${encodeURIComponent(rdkitSvg)}`
                : renderSource === 'crop' && sourceImageUrl
                  ? sourceImageUrl
                  : ''}
              alt={name ?? smiles}
              width={size}
              height={size}
              onError={handleStructureImageError}
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              transition={{ duration: 0.2 }}
              className="mol-display-img"
            />
            {renderSource === 'crop' && (
              <div className="mol-display-fallback-tag" role="status">
                <AlertIcon size={13} /> 原始图片 · 待人工矫正
              </div>
            )}
          </>
        )}
      </div>

      <div className={`mol-display-smiles ${effectiveError ? 'mol-display-smiles--error' : ''}`}>
        {smiles}
      </div>

      {showMetadata && (formula || mw) && (
        <div className="mol-display-metadata">
          {formula && <span>分子式：<strong className="mol-mono">{formula}</strong></span>}
          {mw && <span>分子量：<strong>{mw} g/mol</strong></span>}
        </div>
      )}

      <div className="mol-display-toolbar">
        {mode === 'edit' && !isEditing && (
          <Button
            size="sm"
            variant="ghost"
            className="mol-toolbar-btn mol-toolbar-btn--edit"
            onClick={(event) => {
              event.stopPropagation()
              startEdit()
            }}
          >
            <svg width={12} height={12} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
              <path d="M12 20h9" />
              <path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z" />
            </svg>
            手动编辑
          </Button>
        )}
      </div>
    </div>
  )
}
