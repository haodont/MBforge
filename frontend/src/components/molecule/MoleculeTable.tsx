import { useRef, useEffect, useCallback, memo } from 'react'
import { useTranslation } from 'react-i18next'
import type { MoleculeRecord } from '@/types'
import type {
  MoleculeSort,
  MoleculeSortField,
} from '@/hooks/useMoleculeLibrary'
import Skeleton from '@/components/ui/Skeleton'
import EmptyState from '@/components/ui/EmptyState'
import Button from '@/components/ui/Button'
import Badge, { type BadgeTone } from '@/components/ui/Badge'
import { useOptionalAppContext } from '@/context/AppContext'
import './MoleculeTable.css'

interface MoleculeTableProps {
  molecules: MoleculeRecord[]
  loading: boolean
  selectedIds: Set<string>
  sort: MoleculeSort
  onSort: (field: MoleculeSortField) => void
  onToggleSelect: (molId: string) => void
  onSelectRange: (startId: string, endId: string) => void
  onRowClick: (mol: MoleculeRecord) => void
  lastClickedId: string | null
  setLastClickedId: (id: string | null) => void
}

const headers: { key: MoleculeSortField; label: string }[] = [
  { key: 'name', label: 'Name' },
  { key: 'activity', label: 'Activity' },
  { key: 'status', label: 'Status' },
  { key: 'created_at', label: 'Created' },
]

export default function MoleculeTable({
  molecules,
  loading,
  selectedIds,
  sort,
  onSort,
  onToggleSelect,
  onSelectRange,
  onRowClick,
  lastClickedId,
  setLastClickedId,
}: MoleculeTableProps) {
  const { t } = useTranslation()
  const appContext = useOptionalAppContext()
  const libraryRoot = appContext?.libraryRoot ?? ''
  const lastClickedIdRef = useRef<string | null>(lastClickedId)

  useEffect(() => {
    lastClickedIdRef.current = lastClickedId
  }, [lastClickedId])

  const allSelected = molecules.length > 0 && molecules.every((m) => selectedIds.has(m.mol_id))

  const handleOpenSource = useCallback((event: React.MouseEvent, mol: MoleculeRecord) => {
    event.stopPropagation()
    if (!libraryRoot) return
    const evidence = mol.evidence?.[0]
    const docId = evidence?.doc_id || mol.source_doc
    if (!docId) return
    const sourcePath = `storage/${docId}/source.pdf`
    appContext?.openTab({
      type: 'document',
      title: docId,
      doc: {
        doc_id: docId,
        path: sourcePath,
        source_path: sourcePath,
        doc_type: 'pdf',
        title: docId,
        added_at: new Date().toISOString(),
        hash: '',
      },
      libraryRoot,
      initialPage: evidence?.page ?? undefined,
      initialBbox: evidence?.bbox
        ? [evidence.bbox.x0, evidence.bbox.y0, evidence.bbox.x1, evidence.bbox.y1]
        : undefined,
    })
  }, [appContext, libraryRoot])

  const handleHeaderCheckboxChange = () => {
    if (allSelected) {
      molecules.forEach((m) => onToggleSelect(m.mol_id))
    } else {
      molecules.forEach((m) => {
        if (!selectedIds.has(m.mol_id)) onToggleSelect(m.mol_id)
      })
    }
  }

  if (loading) {
    return (
      <div style={{ padding: '16px 0' }}>
        <Skeleton variant="row" count={8} />
      </div>
    )
  }

  if (molecules.length === 0) {
    return <EmptyState message={t('mol.empty')} />
  }

  return (
    <div className="molecule-table-wrapper">
      <table className="molecule-table">
        <thead>
          <tr className="molecule-table-header-row">
            <th className="molecule-table-checkbox-header" scope="col">
              <input
                type="checkbox"
                checked={allSelected}
                onChange={handleHeaderCheckboxChange}
                aria-label="Select all molecules"
              />
            </th>
            {headers.map((h) => (
              <th
                key={h.key}
                scope="col"
                className="molecule-table-header-cell"
                aria-sort={sort.field === h.key ? (sort.direction === 'asc' ? 'ascending' : 'descending') : 'none'}
              >
                <Button
                  variant="ghost"
                  size="sm"
                  className="molecule-table-sort-button"
                  onClick={() => onSort(h.key)}
                >
                  {h.label}
                  <span className="molecule-table-sort-indicator" aria-hidden>
                    {sort.field === h.key ? (sort.direction === 'asc' ? '↑' : '↓') : '↕'}
                  </span>
                </Button>
              </th>
            ))}
            <th className="molecule-table-source-header" scope="col">
              Source
            </th>
          </tr>
        </thead>
        <tbody>
          {molecules.map((mol) => (
            <MoleculeTableRow
              key={mol.mol_id}
              molecule={mol}
              selected={selectedIds.has(mol.mol_id)}
              lastClickedIdRef={lastClickedIdRef}
              onRowClick={onRowClick}
              onToggleSelect={onToggleSelect}
              onSelectRange={onSelectRange}
              setLastClickedId={setLastClickedId}
              onOpenSource={handleOpenSource}
            />
          ))}
        </tbody>
      </table>
    </div>
  )
}

interface MoleculeTableRowProps {
  molecule: MoleculeRecord
  selected: boolean
  lastClickedIdRef: React.RefObject<string | null>
  onRowClick: (mol: MoleculeRecord) => void
  onToggleSelect: (molId: string) => void
  onSelectRange: (startId: string, endId: string) => void
  setLastClickedId: (id: string | null) => void
  onOpenSource: (event: React.MouseEvent, mol: MoleculeRecord) => void
}

const MoleculeTableRow = memo(function MoleculeTableRow({
  molecule,
  selected,
  lastClickedIdRef,
  onRowClick,
  onToggleSelect,
  onSelectRange,
  setLastClickedId,
  onOpenSource,
}: MoleculeTableRowProps) {
  const { t } = useTranslation()
  const shiftKeyRef = useRef(false)

  const handleCheckboxMouseDown = (e: React.MouseEvent<HTMLInputElement>) => {
    shiftKeyRef.current = e.shiftKey
  }

  const handleCheckboxKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    shiftKeyRef.current = e.shiftKey
  }

  const handleCheckboxClick = (e: React.MouseEvent<HTMLInputElement>) => {
    e.stopPropagation()
  }

  const handleCheckboxChange = () => {
    if (shiftKeyRef.current && lastClickedIdRef.current) {
      onSelectRange(lastClickedIdRef.current, molecule.mol_id)
    } else {
      onToggleSelect(molecule.mol_id)
      setLastClickedId(molecule.mol_id)
    }
    shiftKeyRef.current = false
  }

  const handleRowKeyDown = (e: React.KeyboardEvent<HTMLTableRowElement>) => {
    if ((e.target as HTMLElement).closest('input, button, select, textarea')) return
    if (e.key === 'Enter') {
      e.preventDefault()
      onRowClick(molecule)
    } else if (e.key === ' ') {
      e.preventDefault()
      if (e.shiftKey && lastClickedIdRef.current) {
        onSelectRange(lastClickedIdRef.current, molecule.mol_id)
      } else {
        onToggleSelect(molecule.mol_id)
        setLastClickedId(molecule.mol_id)
      }
    }
  }

  return (
    <tr
      onClick={() => onRowClick(molecule)}
      onKeyDown={handleRowKeyDown}
      tabIndex={0}
      className={`molecule-table-row ${selected ? 'selected' : ''}`}
    >
      <td className="molecule-table-checkbox-cell">
        <input
          type="checkbox"
          checked={selected}
          onMouseDown={handleCheckboxMouseDown}
          onKeyDown={handleCheckboxKeyDown}
          onClick={handleCheckboxClick}
          onChange={handleCheckboxChange}
          aria-label={`Select ${molecule.name || molecule.mol_id}`}
        />
      </td>
      <td className="molecule-table-cell">
        <div className="molecule-table-name">{molecule.name || molecule.mol_id}</div>
        <div className="molecule-table-esmiles">
          {molecule.esmiles}
        </div>
      </td>
      <td className="molecule-table-cell">
        {molecule.activity !== null
          ? `${molecule.activity.toFixed(2)} ${molecule.units || 'nM'}`
          : <span className="activity-missing-badge">{t('mol.activityMissing')}</span>}
      </td>
      <td className="molecule-table-cell">
        <StatusBadge status={molecule.status} label={t(`mol.status.${molecule.status}`)} />
      </td>
      <td className="molecule-table-cell molecule-table-muted-cell">
        {new Date(molecule.created_at).toLocaleDateString()}
      </td>
      <td className="molecule-table-cell molecule-table-muted-cell">
        {molecule.source_doc ? (
          <Button
            variant="ghost"
            size="sm"
            className="molecule-table-source-link"
            onClick={(event) => onOpenSource(event, molecule)}
          >
            {molecule.source_doc}
          </Button>
        ) : '-'}
      </td>
    </tr>
  )
})

function StatusBadge({ status, label }: { status: string; label: string }) {
  const toneMap: Record<string, BadgeTone> = {
    confirmed: 'success',
    pending: 'warning',
    corrected: 'info',
    rejected: 'danger',
  }
  const colorClass: Record<string, string> = {
    confirmed: 'status-badge-confirmed',
    pending: 'status-badge-pending',
    corrected: 'status-badge-corrected',
    rejected: 'status-badge-rejected',
  }
  const badgeClass = colorClass[status] || 'status-badge-default'
  return (
    <Badge
      tone={toneMap[status] ?? 'neutral'}
      className={`status-badge ${badgeClass}`}
      title={status === 'pending' ? '模型自动识别结果，尚未人工修正' : undefined}
    >
      {label}
    </Badge>
  )
}
