import { useState, useEffect, useRef, useCallback } from 'react'
import { validateSmiles, type ValidationIssue } from '../api/http/molecule'
import { basicValidate, estimateFormula, estimateMW } from '../components/molecule/moleculeUtils'
import { getUserFacingError } from '@/utils/errors'

export interface UseMoleculeDisplayReturn {
  imgError: boolean
  setImgError: (v: boolean) => void
  isEditing: boolean
  draftSmiles: string
  validationMsg: string | null
  backendIssue: ValidationIssue | null
  backendLoading: boolean
  effectiveError: string | null
  validation: ReturnType<typeof basicValidate>
  formula: string | null
  mw: number | null
  handleStartEdit: () => void
  handleApplyEdit: () => { success: boolean; message?: string }
  handleCancelEdit: () => void
  handleKeyDown: (e: React.KeyboardEvent<HTMLInputElement>) => void
  setDraftSmiles: (v: string) => void
  setValidationMsg: (v: string | null) => void
}

/**
 * 封装 MoleculeDisplay 的复杂状态逻辑。
 *
 * 管理：
 * - 图像加载状态
 * - 编辑模式与草稿 SMILES
 * - 后端结构校验（debounce）
 * - 元数据计算
 */
export function useMoleculeDisplay(
  smiles: string,
  name: string | undefined,
  showMetadata: boolean,
  onChange?: (newSmiles: string) => void,
  onValidate?: (isValid: boolean, message?: string) => void,
  validateRemotely = true,
): UseMoleculeDisplayReturn {
  void name
  const [imgError, setImgError] = useState(false)
  const [isEditing, setIsEditing] = useState(false)
  const [draftSmiles, setDraftSmilesState] = useState(smiles)
  const [validationMsg, setValidationMsg] = useState<string | null>(null)
  const [backendIssue, setBackendIssue] = useState<ValidationIssue | null>(null)
  const [backendLoading, setBackendLoading] = useState(false)
  const backendTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    setDraftSmilesState(smiles)
    setImgError(false)
  }, [smiles])

  useEffect(() => {
    if (backendTimerRef.current) clearTimeout(backendTimerRef.current)
    if (!validateRemotely) {
      setBackendIssue(null)
      setBackendLoading(false)
      return
    }
    setBackendLoading(true)
    backendTimerRef.current = setTimeout(async () => {
      try {
        const resp = await validateSmiles(smiles)
        const errorIssue = resp.issues.find(i => i.severity === 'error') ?? null
        setBackendIssue(errorIssue)
      } catch (err) {
        const message = getUserFacingError(err, '结构转换失败')
        setBackendIssue({
          code: 'NETWORK',
          severity: 'error',
          message: `结构校验失败：${message}`,
        })
      } finally {
        setBackendLoading(false)
      }
    }, 400)
    return () => {
      if (backendTimerRef.current) clearTimeout(backendTimerRef.current)
    }
  }, [smiles, validateRemotely])

  useEffect(() => {
    if (backendIssue) {
      onValidate?.(false, backendIssue.message)
    } else {
      const result = basicValidate(smiles)
      onValidate?.(result.valid, result.message)
    }
  }, [smiles, backendIssue, onValidate])

  const handleStartEdit = useCallback(() => {
    setIsEditing(true)
    setTimeout(() => inputRef.current?.focus(), 50)
  }, [])

  const handleApplyEdit = useCallback(() => {
    const trimmed = draftSmiles.trim()
    const result = basicValidate(trimmed)
    if (!result.valid) {
      setValidationMsg(result.message ?? '格式错误')
      return { success: false, message: result.message ?? '格式错误' }
    }
    if (backendLoading) {
      setValidationMsg('正在校验…')
      return { success: false, message: '正在校验…' }
    }
    if (backendIssue && backendIssue.severity === 'error') {
      setValidationMsg(backendIssue.message)
      return { success: false, message: backendIssue.message }
    }
    onChange?.(trimmed)
    setIsEditing(false)
    setValidationMsg(null)
    setImgError(false)
    return { success: true }
  }, [draftSmiles, backendLoading, backendIssue, onChange])

  const handleCancelEdit = useCallback(() => {
    setDraftSmilesState(smiles)
    setIsEditing(false)
    setValidationMsg(null)
  }, [smiles])

  const handleKeyDown = useCallback((e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') handleApplyEdit()
    else if (e.key === 'Escape') handleCancelEdit()
  }, [handleApplyEdit, handleCancelEdit])

  const setDraftSmiles = useCallback((v: string) => {
    setDraftSmilesState(v)
    setValidationMsg(null)
  }, [])

  const formula = showMetadata ? estimateFormula(smiles) : null
  const mw = showMetadata ? estimateMW(smiles) : null
  const validation = basicValidate(smiles)
  const effectiveError: string | null =
    validationMsg
    ?? (validation.valid ? null : validation.message)
    ?? (backendIssue?.severity === 'error' ? backendIssue.message : null)

  return {
    imgError,
    setImgError,
    isEditing,
    draftSmiles,
    validationMsg,
    backendIssue,
    backendLoading,
    effectiveError,
    validation,
    formula,
    mw,
    handleStartEdit,
    handleApplyEdit,
    handleCancelEdit,
    handleKeyDown,
    setDraftSmiles,
    setValidationMsg,
  }
}
