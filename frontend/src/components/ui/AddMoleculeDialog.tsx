import { useState, ChangeEvent, useEffect } from 'react'
import type { SyntheticEvent } from 'react'
import { molAdminAdd, molAdminSearchBySmiles } from '../../api/http/molecule_admin'
import { chemValidateSmiles } from '../../api/http/molecule'
import type { MoleculeRecord } from '../../types'
import Button from './Button'
import Input from './Input'
import Modal from './Modal'
import { getUserFacingError } from '@/utils/errors'

function generateMolId(): string {
  return `mol_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`
}

interface AddMoleculeDialogProps {
  open: boolean
  onClose: () => void
  libraryRoot: string
  onAdded?: () => void
}

export function AddMoleculeDialog({ open, onClose, libraryRoot, onAdded }: AddMoleculeDialogProps) {
  const [esmiles, setEsmiles] = useState('')
  const [name, setName] = useState('')
  const [activity, setActivity] = useState('')
  const [activityType, setActivityType] = useState('IC50')
  const [units, setUnits] = useState('nM')
  const [sourceType, setSourceType] = useState('manual')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [duplicateWarning, setDuplicateWarning] = useState<string | null>(null)

  // Clear state when dialog opens
  useEffect(() => {
    if (open) {
      setEsmiles('')
      setName('')
      setActivity('')
      setActivityType('IC50')
      setUnits('nM')
      setSourceType('manual')
      setError(null)
      setDuplicateWarning(null)
    }
  }, [open])

  const handleEsmilesChange = async (value: string) => {
    setEsmiles(value)
    setError(null)
    setDuplicateWarning(null)

    const trimmed = value.trim()
    if (trimmed.length === 0) return

    // [B.1] 实时 SMILES 校验 — 走 Rust chematic，零后端依赖
    if (trimmed.length > 1) {
      try {
        const v = await chemValidateSmiles(trimmed)
        if (!v.valid) {
          setError(v.error ?? 'Invalid SMILES')
        } else if (v.canonical_smiles && v.canonical_smiles !== trimmed) {
          // 自动规范化：原始输入不合法但 canonical 形式合法时替换
          setEsmiles(v.canonical_smiles)
        }
      } catch {
        // 静默：用户输入还没敲完，不要每按一个键就 Toast
      }
    }

    if (trimmed.length > 5) {
      try {
        const existing = await molAdminSearchBySmiles(libraryRoot, trimmed)
        if (existing) {
          setDuplicateWarning(`Molecule already exists as "${existing.name}" (${existing.mol_id})`)
        }
      } catch {
        // Ignore search errors
      }
    }
  }

  const handleSubmit = async (e: SyntheticEvent) => {
    e.preventDefault()
    if (!esmiles.trim()) {
      setError('SMILES is required')
      return
    }

    // [B.1] 提交前最后一次 chematic 校验 — 阻止非法 SMILES 写入 store
    try {
      const v = await chemValidateSmiles(esmiles.trim())
      if (!v.valid) {
        setError(v.error ?? 'Invalid SMILES')
        return
      }
    } catch (err) {
      setError(getUserFacingError(err, 'SMILES validation failed'))
      return
    }

    setLoading(true)
    setError(null)

    try {
      const molId = generateMolId()
      const record: MoleculeRecord = {
        mol_id: molId,
        esmiles: esmiles.trim(),
        name: name.trim(),
        source_doc: '',
        source_type: sourceType,
        activity: activity ? parseFloat(activity) : null,
        activity_type: activityType,
        units: units,
        status: 'pending',
        properties: {},
        tags: [],
        notes: '',
        created_at: new Date().toISOString(),
      }
      await molAdminAdd(libraryRoot, record)
      onAdded?.()
      handleClose()
    } catch (err) {
      setError(getUserFacingError(err))
    } finally {
      setLoading(false)
    }
  }

  const handleClose = () => {
    setEsmiles('')
    setName('')
    setActivity('')
    setActivityType('IC50')
    setUnits('nM')
    setSourceType('manual')
    setError(null)
    setDuplicateWarning(null)
    onClose()
  }

  return (
    <Modal
      open={open}
      onClose={handleClose}
      title="Add Molecule"
      width="90%"
      maxWidth={480}
      height="auto"
      maxHeight={600}
      footer={
        <div className="flex justify-end gap-2">
          <Button variant="secondary" onClick={handleClose}>
            Cancel
          </Button>
          <Button 
            onClick={handleSubmit} 
            disabled={loading || !esmiles.trim()}
          >
            {loading ? 'Adding...' : 'Add Molecule'}
          </Button>
        </div>
      }
    >
      <form onSubmit={handleSubmit} className="space-y-4">
        {error && (
          <div className="p-3 bg-red-500/10 border border-red-500/30 rounded text-red-500 text-sm">
            {error}
          </div>
        )}

        {duplicateWarning && (
          <div className="p-3 bg-yellow-500/10 border border-yellow-500/30 rounded text-yellow-500 text-sm">
            {duplicateWarning}
          </div>
        )}

        <div className="space-y-2">
          <label className="text-sm font-medium block">SMILES / E-SMILES *</label>
          <Input
            value={esmiles}
            onChange={(e: ChangeEvent<HTMLInputElement>) => handleEsmilesChange(e.target.value)}
            placeholder="CC(=O)Oc1ccccc1C(=O)O"
            className="font-mono text-sm"
          />
          <p className="text-xs text-muted-foreground">
            Standard SMILES or E-SMILES (with E/Z stereo notation)
          </p>
        </div>

        <div className="space-y-2">
          <label className="text-sm font-medium block">Name</label>
          <Input
            value={name}
            onChange={(e: ChangeEvent<HTMLInputElement>) => setName(e.target.value)}
            placeholder="Aspirin"
          />
        </div>

        <div className="space-y-2">
          <label className="text-sm font-medium block">Source</label>
          <select
            value={sourceType}
            onChange={(e) => setSourceType(e.target.value)}
            className="w-full h-10 px-3 bg-background border border-border rounded-md text-sm"
          >
            <option value="manual">Manual Entry</option>
            <option value="pdf_extraction">PDF Extraction</option>
            <option value="image_detection">Image Detection</option>
            <option value="imported">Imported</option>
          </select>
        </div>

        <div className="grid grid-cols-2 gap-3">
          <div className="space-y-2">
            <label className="text-sm font-medium block">Activity Value</label>
            <Input
              type="number"
              value={activity}
              onChange={(e: ChangeEvent<HTMLInputElement>) => setActivity(e.target.value)}
              placeholder="125.5"
            />
          </div>

          <div className="space-y-2">
            <label className="text-sm font-medium block">Activity Type</label>
            <select
              value={activityType}
              onChange={(e) => setActivityType(e.target.value)}
              className="w-full h-10 px-3 bg-background border border-border rounded-md text-sm"
            >
              <option value="IC50">IC50</option>
              <option value="EC50">EC50</option>
              <option value="Ki">Ki</option>
              <option value="Kd">Kd</option>
              <option value="IC90">IC90</option>
              <option value="GI50">GI50</option>
              <option value="ED50">ED50</option>
              <option value="LD50">LD50</option>
              <option value="OTHER">Other</option>
            </select>
          </div>
        </div>

        <div className="space-y-2">
          <label className="text-sm font-medium block">Units</label>
          <select
            value={units}
            onChange={(e) => setUnits(e.target.value)}
            className="w-full h-10 px-3 bg-background border border-border rounded-md text-sm"
          >
            <option value="nM">nM</option>
            <option value="uM">uM</option>
            <option value="mM">mM</option>
            <option value="M">M</option>
            <option value="ng/mL">ng/mL</option>
            <option value="ug/mL">ug/mL</option>
            <option value="mg/mL">mg/mL</option>
            <option value="percent">%</option>
            <option value="log units">log units</option>
          </select>
        </div>
      </form>
    </Modal>
  )
}
