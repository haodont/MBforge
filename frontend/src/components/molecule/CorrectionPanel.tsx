import { useState, useEffect, useRef } from 'react'
import { motion } from 'framer-motion'
import MoleculeDisplay from './MoleculeDisplay'
import ConfidenceThresholdSlider from './ConfidenceThresholdSlider'
import { useConfidenceThreshold } from '@/hooks/useConfidenceThreshold'
import Button from '@/components/ui/Button'
import { CheckIcon, XIcon, AlertIcon, ChevronLeftIcon, ChevronRightIcon } from '../icons'
import { validateSmiles } from '@/api/http/molecule'
import StatusBadge from './StatusBadge'
import SmilesDiff from './SmilesDiff'
import ValidationResult from './ValidationResult'
import { getUserFacingError } from '@/utils/errors'

export interface CorrectionItem {
  id: string
  ocrSmiles: string
  ocrConfidence: number
  correctedSmiles?: string
  sourceImage?: string
  name?: string
  sourceDoc?: string
  context?: string
  status?: 'pending' | 'confirmed' | 'rejected' | 'corrected'
}

export interface CorrectionPanelProps {
  items: CorrectionItem[]
  onComplete: (results: Array<{ id: string; finalSmiles: string; status: 'confirmed' | 'rejected' | 'corrected' }>) => void
  onItemChange?: (id: string, finalSmiles: string, status: CorrectionItem['status']) => void
  showSourceImage?: boolean
  className?: string
  style?: React.CSSProperties
}

export default function CorrectionPanel({
  items,
  onComplete,
  onItemChange,
  showSourceImage = true,
  className,
  style,
}: CorrectionPanelProps) {
  const [currentIndex, setCurrentIndex] = useState(0)
  const [decisions, setDecisions] = useState<Record<string, {
    status: 'confirmed' | 'rejected' | 'corrected'
    finalSmiles: string
  }>>({})

  const [autoConfirmThreshold] = useConfidenceThreshold()

  const [validation, setValidation] = useState<{
    smiles: string
    issues: import('../../api/http/molecule').ValidationIssue[]
    canonical: string | null
    loading: boolean
  } | null>(null)
  const validationTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const total = items.length
  const current = items[currentIndex]
  const currentDecision = (current.id in decisions ? decisions[current.id] : undefined) as { status: CorrectionItem['status']; finalSmiles: string } | undefined
  const isLast = currentIndex === total - 1
  const isFirst = currentIndex === 0

  const currentFinalSmiles = currentDecision?.finalSmiles ?? current.correctedSmiles ?? current.ocrSmiles

  useEffect(() => {
    if (!currentFinalSmiles || currentFinalSmiles === current.ocrSmiles) {
      setValidation(null)
      return
    }
    if (validationTimerRef.current) clearTimeout(validationTimerRef.current)
    setValidation(prev => prev ? { ...prev, loading: true } : { smiles: currentFinalSmiles, issues: [], canonical: null, loading: true })
    validationTimerRef.current = setTimeout(async () => {
      try {
        const resp = await validateSmiles(currentFinalSmiles)
        setValidation({
          smiles: currentFinalSmiles,
          issues: resp.issues,
          canonical: resp.canonical_smiles,
          loading: false,
        })
      } catch (err) {
        const message = getUserFacingError(err, '校正失败')
        setValidation({
          smiles: currentFinalSmiles,
          issues: [{ code: 'NETWORK', severity: 'error', message: `结构校验失败：${message}` }],
          canonical: null,
          loading: false,
        })
      }
    }, 600)
    return () => {
      if (validationTimerRef.current) clearTimeout(validationTimerRef.current)
    }
  }, [currentFinalSmiles, current.ocrSmiles])

  if (total === 0) {
    return (
      <div className={`${className ?? ''} mol-correction-empty`} style={style}>
        没有待矫正的分子
      </div>
    )
  }
  const isOcrConfident = current.ocrConfidence >= autoConfirmThreshold

  const updateDecision = (status: 'confirmed' | 'rejected' | 'corrected', smiles?: string) => {
    const finalSmiles = smiles ?? currentFinalSmiles
    setDecisions(prev => ({
      ...prev,
      [current.id]: { status, finalSmiles },
    }))
    onItemChange?.(current.id, finalSmiles, status)
  }

  const handleSmilesEdit = (newSmiles: string) => {
    updateDecision('corrected', newSmiles)
  }

  const currentStatus: CorrectionItem['status'] = currentDecision?.status ?? current.status ?? 'pending'

  const handleConfirm = () => updateDecision('confirmed', currentFinalSmiles)
  const handleReject = () => updateDecision('rejected', currentFinalSmiles)
  const goPrev = () => { if (!isFirst) setCurrentIndex(i => i - 1) }
  const goNext = () => { if (!isLast) setCurrentIndex(i => i + 1) }

  const handleFinish = () => {
    const results = items.map(item => {
      if (item.id in decisions) {
        const d = decisions[item.id]
        return { id: item.id, finalSmiles: d.finalSmiles, status: d.status }
      }
      return {
        id: item.id,
        finalSmiles: item.ocrSmiles,
        status: item.ocrConfidence >= autoConfirmThreshold ? 'confirmed' as const : 'rejected' as const,
      }
    })
    onComplete(results)
  }

  const progress = ((currentIndex + 1) / total) * 100
  const decidedCount = Object.keys(decisions).length
  const allDecided = decidedCount === total

  return (
    <div className={`${className ?? ''} mol-correction-panel`} style={style}>
      {/* 顶部进度条 */}
      <div className="mol-correction-progress-wrap">
        <div className="mol-correction-progress-header">
          <div className="mol-correction-progress-title">
            分子矫正（{currentIndex + 1} / {total}）
          </div>
          <div className="mol-correction-progress-meta">
            <span className="mol-correction-progress-count">已处理 {decidedCount} / {total}</span>
            <StatusBadge status={currentStatus} />
          </div>
        </div>
        <div className="mol-correction-progress-bar">
          <motion.div
            className="mol-correction-progress-fill"
            initial={{ width: 0 }}
            animate={{ width: `${progress}%` }}
            transition={{ duration: 0.3 }}
          />
        </div>
      </div>

      <ConfidenceThresholdSlider />

      {/* 主体：并排对比 */}
      <div className="mol-correction-grid" data-source-image={showSourceImage}>
        {showSourceImage && (
          <div className="mol-correction-source">
            <div className="mol-correction-source-label">文献原图</div>
            {current.sourceImage ? (
              <div className="mol-correction-source-img-wrap">
                <img src={current.sourceImage} alt="来源图像" className="mol-correction-source-img" />
              </div>
            ) : (
              <div className="mol-correction-source-img-wrap mol-correction-source-img-wrap--empty">
                （原图不可用）
              </div>
            )}
            {current.context && (
              <div className="mol-correction-source-context">{current.context}</div>
            )}
          </div>
        )}

        <MoleculeDisplay
          smiles={current.ocrSmiles}
          name="OCR 识别结果"
          source={`置信度 ${Math.round(current.ocrConfidence * 100)}%`}
          confidence={current.ocrConfidence}
          showMetadata
          mode="view"
        />

        <div className="mol-correction-result-wrap">
          <MoleculeDisplay
            smiles={currentFinalSmiles}
            name={current.name ?? '最终结果'}
            source={currentDecision?.status === 'corrected' ? '人工修正' : '待定'}
            confidence={currentDecision?.status === 'corrected' ? 1.0 : current.ocrConfidence}
            showMetadata
            mode="edit"
            onChange={handleSmilesEdit}
          />
          {currentStatus === 'corrected' && current.ocrSmiles !== currentFinalSmiles && (
            <div className="mol-correction-diff">
              <SmilesDiff before={current.ocrSmiles} after={currentFinalSmiles} />
            </div>
          )}
          <div className="mol-correction-validation">
            <ValidationResult
              validation={validation}
              onUseCanonical={canonical => handleSmilesEdit(canonical)}
            />
          </div>
        </div>
      </div>

      {!isOcrConfident && (
        <div className="mol-correction-warning">
          <AlertIcon size={14} />
          <span>OCR 置信度 {Math.round(current.ocrConfidence * 100)}% 低于阈值 {Math.round(autoConfirmThreshold * 100)}%，建议仔细核对分子结构。</span>
        </div>
      )}

      <div className="mol-correction-actions">
        <div className="mol-correction-nav">
          <Button variant="secondary" size="sm" onClick={goPrev} disabled={isFirst}>
            <ChevronLeftIcon size={14} /> 上一项
          </Button>
          <Button variant="secondary" size="sm" onClick={goNext} disabled={isLast}>
            下一项 <ChevronRightIcon size={14} />
          </Button>
        </div>

        <div className="mol-correction-decisions">
          <Button variant="danger" size="sm" onClick={handleReject}>
            <XIcon size={14} /> 拒绝
          </Button>
          <Button variant="primary" size="sm" onClick={handleConfirm}>
            <CheckIcon size={14} /> 确认
          </Button>
          <Button
            variant="primary"
            onClick={handleFinish}
            disabled={!allDecided}
            title={allDecided ? '保存所有决定' : `还有 ${total - decidedCount} 项未处理`}
          >
            完成矫正（{decidedCount}/{total}）
          </Button>
        </div>
      </div>
    </div>
  )
}
