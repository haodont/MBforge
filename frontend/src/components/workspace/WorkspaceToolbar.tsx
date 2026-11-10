/** Workspace toolbar — summary, bulk delete/export, view toggle, import button. */

import { useTranslation } from 'react-i18next'
import Button from '@/components/ui/Button'
import { DownloadIcon, GridIcon, PlusIcon, TableIcon, TrashIcon } from '@/components/icons'
import type { DocumentInfo } from '@/api/http/library'
import { useActivityExport } from './useActivityExport'

export type ViewMode = 'grid' | 'list'

export interface WorkspaceToolbarProps {
  documents: DocumentInfo[]
  viewMode: ViewMode
  onViewChange: (mode: ViewMode) => void
  allDocumentsSelected: boolean
  selectedDocuments: DocumentInfo[]
  onToggleSelectAll: () => void
  onRequestDeleteSelected: (docs: DocumentInfo[]) => void
  deletePending: boolean
  libraryRoot: string
  onImport: () => void
  /** An import is running — disables the import button. */
  importBusy: boolean
}

export default function WorkspaceToolbar({
  documents,
  viewMode,
  onViewChange,
  allDocumentsSelected,
  selectedDocuments,
  onToggleSelectAll,
  onRequestDeleteSelected,
  deletePending,
  libraryRoot,
  onImport,
  importBusy,
}: WorkspaceToolbarProps) {
  const { t } = useTranslation()
  const { exportPending, handleExport } = useActivityExport(libraryRoot)
  const totalPages = documents.reduce((total, doc) => total + Math.max(0, doc.page_count), 0)

  return (
    <div className="workspace-toolbar">
      <div className="workspace-summary" aria-label={t('workspace.summary')}>
        <span>{t('workspace.documentCount', { count: documents.length })}</span>
        <span>{t('workspace.pageCount', { count: totalPages })}</span>
      </div>
      <div className="workspace-toolbar-actions">
        {documents.length > 0 && (
          <div className="workspace-bulk-actions">
            <Button
              variant="ghost"
              size="sm"
              ariaPressed={allDocumentsSelected}
              onClick={onToggleSelectAll}
              disabled={deletePending}
            >
              {allDocumentsSelected ? t('workspace.deselectAll') : t('workspace.selectAll')}
            </Button>
            {selectedDocuments.length > 0 && (
              <Button
                variant="secondary"
                size="sm"
                icon={<DownloadIcon size={16} />}
                onClick={() => void handleExport(selectedDocuments.map(doc => doc.doc_id))}
                disabled={exportPending || deletePending || !libraryRoot}
              >
                {exportPending
                  ? t('workspace.activityExportPending')
                  : t('workspace.activityExportSelected', { count: selectedDocuments.length })}
              </Button>
            )}
            {selectedDocuments.length > 0 && (
              <Button
                variant="danger"
                size="sm"
                icon={<TrashIcon size={16} />}
                onClick={() => onRequestDeleteSelected(selectedDocuments)}
                disabled={deletePending}
              >
                {t('workspace.deleteSelected', { count: selectedDocuments.length })}
              </Button>
            )}
          </div>
        )}
        <span className="workspace-view-label">{viewMode === 'grid' ? t('workspace.viewGrid') : t('workspace.viewList')}</span>
        <div
          className="workspace-view-toggle"
          role="group"
          aria-label={t('workspace.documents')}
        >
          <Button
            variant="ghost"
            size="sm"
            ariaPressed={viewMode === 'grid'}
            ariaLabel={t('workspace.viewGrid')}
            title={t('workspace.viewGrid')}
            className={`workspace-view-toggle__btn${viewMode === 'grid' ? ' is-active' : ''}`}
            onClick={() => onViewChange('grid')}
          >
            <GridIcon size={16} />
          </Button>
          <Button
            variant="ghost"
            size="sm"
            ariaPressed={viewMode === 'list'}
            ariaLabel={t('workspace.viewList')}
            title={t('workspace.viewList')}
            className={`workspace-view-toggle__btn${viewMode === 'list' ? ' is-active' : ''}`}
            onClick={() => onViewChange('list')}
          >
            <TableIcon size={16} />
          </Button>
        </div>
        <Button
          variant="secondary"
          size="sm"
          icon={<PlusIcon size={16} />}
          className="workspace-import-btn"
          onClick={onImport}
          disabled={importBusy}
        >
          {importBusy ? t('library.importing') : t('library.importPdf')}
        </Button>
      </div>
    </div>
  )
}
