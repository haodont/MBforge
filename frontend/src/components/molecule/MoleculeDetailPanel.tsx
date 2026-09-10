import { useState, useEffect, useCallback, useMemo } from 'react'
import { chemDescriptors } from '@/api/http/molecule'
import { molAdminUpdate } from '@/api/http/molecule_admin'
import { toast } from '@/hooks/useToast'
import type { EvidenceItem, ExtractionResult, MoleculeRecord } from '@/types'
import MoleculeEditorDialog from './MoleculeEditorDialog'
import EvidencePanel from './EvidencePanel'
import DetectionHeader from './detail/DetectionHeader'
import MoleculeRecordForm from './detail/MoleculeRecordForm'
import ReadOnlyMeta from './detail/ReadOnlyMeta'
import RelatedTextPanel from './detail/RelatedTextPanel'
import DescGrid, { type ChemDescriptors } from './detail/DescGrid'
import FormField from './detail/FormField'
import TextArea from '@/components/ui/TextArea'

interface BaseProps {
  libraryRoot?: string | null
  onOpenPdf?: (docId: string, page: number | null, bbox: EvidenceItem['bbox']) => void
}
interface DetectionProps extends BaseProps {
  detection: ExtractionResult
  index: number
  onSave: (newSmiles: string) => void
  molecule?: never
  onSaved?: never
}

interface MoleculeProps extends BaseProps {
  molecule: MoleculeRecord
  onSaved?: () => void
  detection?: never
  index?: never
  onSave?: never
}

type MoleculeDetailPanelProps = DetectionProps | MoleculeProps

/**
 * 分子详情面板
 *
 * 兼容两种模式：
 * - Detection 模式：展示 ExtractionResult，保留原有编辑按钮与置信度展示。
 * - MoleculeRecord 模式：提供可编辑表单，通过 molAdminUpdate 持久化。
 *
 * 两种模式均显示理化性质；记录模式中的 E-SMILES 仅在编辑字段显示。
 */
export default function MoleculeDetailPanel(props: MoleculeDetailPanelProps) {
  const { detection, molecule, libraryRoot } = props
  const isMoleculeMode = Boolean(molecule)

  // Detection 模式：结构编辑器弹窗
  const [showEditor, setShowEditor] = useState(false)

  // MoleculeRecord 模式：本地编辑状态
  const [edited, setEdited] = useState<MoleculeRecord | null>(
    molecule ? { ...molecule } : null
  )
  const [saving, setSaving] = useState(false)

  // 当 molecule 变化时重置表单
  useEffect(() => {
    if (molecule) setEdited({ ...molecule })
  }, [molecule])

  // 用于 descriptors 的当前结构。RDKit 只能解析纯 SMILES，
  // 故优先 Layer1 `smiles`；esmiles 可能含 <sep> 标签。
  const displayEsmiles = isMoleculeMode
    ? (edited?.smiles || edited?.esmiles)
    : (detection?.smiles || detection?.esmiles)

  const [descriptors, setDescriptors] = useState<ChemDescriptors | null>(null)
  const [descLoading, setDescLoading] = useState(false)

  // 获取理化性质
  useEffect(() => {
    if (!displayEsmiles) return
    setDescLoading(true)
    chemDescriptors(displayEsmiles)
      .then(setDescriptors)
      .catch(() => setDescriptors(null))
      .finally(() => setDescLoading(false))
  }, [displayEsmiles])

  const handleEditorSave = useCallback(async (newSmiles: string) => {
    if (detection) {
      ;(props).onSave(newSmiles)
      setShowEditor(false)
      return
    }

    if (!libraryRoot || !edited) {
      toast.error('未指定项目根目录，无法保存')
      throw new Error('Missing library root or molecule record')
    }

    try {
      const updated = { ...edited, esmiles: newSmiles, status: 'corrected' }
      const success = await molAdminUpdate(libraryRoot, updated)
      if (!success) {
        throw new Error('Failed to save molecule structure')
      }
      setEdited(updated)
      toast.success('分子结构已修正')
      props.onSaved?.()
      setShowEditor(false)
    } catch (error) {
      toast.error(error instanceof Error ? error.message : '结构保存失败')
      throw error
    }
  }, [detection, edited, libraryRoot, props])

  // MoleculeRecord 模式：保存编辑后的记录
  const handleSaveRecord = async () => {
    if (!libraryRoot) {
      toast.error('未指定项目根目录，无法保存')
      return
    }
    if (!edited) return
    setSaving(true)
    try {
      const success = await molAdminUpdate(libraryRoot, edited)
      if (success) {
        toast.success('分子记录已更新')
        ;(props as MoleculeProps).onSaved?.()
      } else {
        toast.error('保存失败')
      }
    } catch (e) {
      toast.error(e instanceof Error ? e.message : '保存失败')
    } finally {
      setSaving(false)
    }
  }

  const handleFieldChange = <K extends keyof MoleculeRecord>(
    field: K,
    value: MoleculeRecord[K]
  ) => {
    setEdited(prev => (prev ? { ...prev, [field]: value } : null))
  }

  const relatedTexts = useMemo(
    () => Array.from(new Set(
      molecule?.evidence
        ?.map((item) => item.context_text?.trim())
        .filter((text): text is string => Boolean(text)) ?? [],
    )),
    [molecule?.evidence],
  )
  const originalImageUrl = useMemo(
    () => molecule?.evidence?.find((item) => item.kind === 'figure' && item.crop_url)?.crop_url ?? null,
    [molecule?.evidence],
  )

  return (
    <>
      <div
        data-testid="molecule-detail-panel"
        className="molecule-detail-panel"
      >
        {isMoleculeMode && edited ? (
          <MoleculeRecordForm
            record={edited}
            saving={saving}
            onChange={handleFieldChange}
            onSave={handleSaveRecord}
            onEditStructure={() => setShowEditor(true)}
            evidence={
              molecule?.evidence && molecule.evidence.length > 0 ? (
                <EvidencePanel
                  items={molecule.evidence}
                  esmiles={edited.smiles || edited.esmiles}
                  libraryRoot={libraryRoot ?? null}
                  molId={molecule.mol_id}
                  evidenceTotal={molecule.evidence_total}
                  onOpenPdf={(docId, page, bbox) => props.onOpenPdf?.(docId, page, bbox)}
                />
              ) : null
            }
          />
        ) : detection ? (
          <DetectionHeader
            detection={detection}
            index={(props).index}
            onEdit={() => setShowEditor(true)}
          />
        ) : null}

        <section>
          <div className="molecule-detail-panel__section-header">
            <div className="molecule-detail-panel__section-title">
              理化性质
            </div>
            <span className="molecule-detail-panel__section-hint">基于当前 E-SMILES</span>
          </div>
          <div className="molecule-detail-panel__desc-grid">
            <DescGrid descriptors={descriptors} loading={descLoading} />
          </div>
        </section>

        {/* Detection mode has no editable record form, so retain its E-SMILES here. */}
        {!isMoleculeMode && displayEsmiles && (
          <div>
            <div className="molecule-detail-panel__esmiles-label">
              E-SMILES
            </div>
            <div className="molecule-detail-panel__esmiles-block">
              {displayEsmiles}
            </div>
          </div>
        )}

        {/* MoleculeRecord 模式下的只读元信息 */}
        {isMoleculeMode && molecule && (
          <ReadOnlyMeta record={molecule} />
        )}

        {isMoleculeMode && relatedTexts.length > 0 && (
          <RelatedTextPanel texts={relatedTexts} />
        )}

        {/* Detection 模式下的文献上下文 */}
        {!isMoleculeMode && detection?.context_text && (
          <div>
            <div className="molecule-detail-panel__context-label">
              文献上下文
            </div>
            <div className="molecule-detail-panel__context-block">
              {detection.context_text}
            </div>
          </div>
        )}


        {isMoleculeMode && edited && (
          <FormField label="备注">
            <TextArea
              value={edited.notes || ''}
              onChange={e => handleFieldChange('notes', e.target.value)}
              rows={4}
              className="molecule-detail-panel__notes"
            />
          </FormField>
        )}
      </div>

      {showEditor && (detection || edited) && (
        <MoleculeEditorDialog
          smiles={detection?.esmiles ?? edited?.esmiles ?? ''}
          name={detection?.name ?? edited?.name}
          originalImageUrl={originalImageUrl}
          onSave={handleEditorSave}
          onClose={() => setShowEditor(false)}
        />
      )}
    </>
  )
}
