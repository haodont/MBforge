/** Workspace document row (list view). */

import { useTranslation } from 'react-i18next'
import { PdfIcon } from '@/components/icons'
import DocumentActionMenu from './DocumentActionMenu'
import type { DocumentItemProps } from './DocumentCard'

export default function DocumentRow({
  doc,
  deletePending,
  patentPending,
  onOpen,
  onDelete,
  onPatentAnalyze,
  selected,
  onToggleSelect,
  statusBadge,
}: DocumentItemProps) {
  const { t } = useTranslation()
  return (
    <div className={`doc-list__row${selected ? ' is-selected' : ''}`} role="listitem">
      <label className="doc-list__select">
        <input
          type="checkbox"
          aria-label={t('workspace.selectDocument', { filename: doc.file_name })}
          checked={selected}
          onChange={(event) => onToggleSelect(doc, event.currentTarget.checked)}
        />
      </label>
      <button
        type="button"
        className="doc-list__main"
        onClick={() => onOpen(doc)}
      >
        <span className="doc-list__icon">
          <PdfIcon size={18} />
        </span>
        <span className="doc-list__title-block">
          <span className="doc-list__title" title={doc.title}>{doc.title}</span>
          <span className="doc-list__file" title={doc.file_name}>{doc.file_name}</span>
        </span>
        <span className="doc-list__pages">
          {doc.page_count > 0
            ? t('workspace.pages', { count: doc.page_count })
            : '—'}
        </span>
        <span className="doc-list__status">{statusBadge(doc)}</span>
      </button>
      <div
        className="doc-list__menu"
        onClick={(event) => event.stopPropagation()}
      >
        <DocumentActionMenu
          doc={doc}
          deletePending={deletePending}
          patentPending={patentPending}
          onDelete={onDelete}
          onPatentAnalyze={onPatentAnalyze}
        />
      </div>
    </div>
  )
}
