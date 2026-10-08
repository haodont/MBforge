/** Workspace document card (grid view). */

import type { ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { PdfIcon } from '@/components/icons'
import type { DocumentInfo } from '@/api/http/library'
import DocumentActionMenu from './DocumentActionMenu'

export type DocumentItemProps = {
  doc: DocumentInfo
  deletePending: boolean
  patentPending: boolean
  onOpen: (doc: DocumentInfo) => void
  onDelete: (doc: DocumentInfo) => void
  onPatentAnalyze: (doc: DocumentInfo) => void
  selected: boolean
  onToggleSelect: (doc: DocumentInfo, selected: boolean) => void
  statusBadge: (doc: DocumentInfo) => ReactNode
}

export default function DocumentCard({
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
    <article className={`doc-card${selected ? ' is-selected' : ''}`}>
      <label className="doc-card-select">
        <input
          type="checkbox"
          aria-label={t('workspace.selectDocument', { filename: doc.file_name })}
          checked={selected}
          onChange={(event) => onToggleSelect(doc, event.currentTarget.checked)}
        />
      </label>
      <div className="doc-card-menu" onClick={(event) => event.stopPropagation()}>
        <DocumentActionMenu
          doc={doc}
          deletePending={deletePending}
          patentPending={patentPending}
          onDelete={onDelete}
          onPatentAnalyze={onPatentAnalyze}
        />
      </div>
      <button
        type="button"
        className="doc-card-open"
        aria-label={doc.title}
        onClick={() => onOpen(doc)}
      >
        <span className="doc-card-icon">
          <PdfIcon size={26} />
        </span>
        <span className="doc-card-info">
          <span className="doc-card-title" title={doc.title}>
            {doc.title}
          </span>
          <span className="doc-card-meta">
            <span>{doc.file_name}</span>
            {doc.page_count > 0 && <span>{t('workspace.pages', { count: doc.page_count })}</span>}
          </span>
        </span>
        <span className="doc-card-status">
          {statusBadge(doc)}
        </span>
      </button>
    </article>
  )
}
