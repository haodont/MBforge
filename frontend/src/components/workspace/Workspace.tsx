import { useCallback, useState } from 'react'
import { motion } from 'framer-motion'
import { useTranslation } from 'react-i18next'
import { fadeUp } from '@/hooks/useAnimations'
import { useAppContext } from '@/context/AppContext'
import { useDocuments } from '@/api/query/hooks'
import { PdfIcon, PlusIcon } from '@/components/icons'
import Button from '@/components/ui/Button'
import ConfirmDialog from '@/components/ui/ConfirmDialog'
import InlineAlert from '@/components/ui/InlineAlert'
import ProgressBar from '@/components/ui/ProgressBar'
import Skeleton from '@/components/ui/Skeleton'
import type { DocumentInfo } from '@/api/http/library'
import DocumentCard from './DocumentCard'
import DocumentRow from './DocumentRow'
import DocumentStatusBadge from './DocumentStatusBadge'
import WorkspaceToolbar, { type ViewMode } from './WorkspaceToolbar'
import { useWorkspaceSelection } from './useWorkspaceSelection'
import { useWorkspaceImport } from './useWorkspaceImport'
import { useWorkspaceQueueStatus } from './useWorkspaceQueueStatus'
import { useWorkspaceMutations } from './useWorkspaceMutations'

export default function Workspace() {
  const { t } = useTranslation()
  const { libraryRoot, openTab } = useAppContext()
  const { data, isLoading, isError } = useDocuments()
  const documents = data?.documents ?? []

  const selection = useWorkspaceSelection(documents)
  const importer = useWorkspaceImport()
  const { processingCount, getDocStatus } = useWorkspaceQueueStatus(libraryRoot)
  const mutations = useWorkspaceMutations({
    libraryRoot,
    removeFromSelection: selection.removeFromSelection,
  })

  const [viewMode, setViewMode] = useState<ViewMode>(() => {
    if (typeof window === 'undefined') return 'grid'
    const stored = window.localStorage.getItem('mbforge.workspace.view')
    return stored === 'list' || stored === 'grid' ? stored : 'grid'
  })

  const setView = useCallback((next: ViewMode) => {
    setViewMode(next)
    if (typeof window !== 'undefined') {
      window.localStorage.setItem('mbforge.workspace.view', next)
    }
  }, [])

  const handleOpenDocument = (doc: DocumentInfo) => {
    openTab({
      type: 'pdf',
      title: doc.title,
      doc: {
        doc_id: doc.doc_id,
        path: doc.file_name,
        doc_type: 'pdf',
        title: doc.title,
      },
      libraryRoot,
    })
  }

  const statusBadge = (doc: DocumentInfo) => {
    const { status, progress } = getDocStatus(doc)
    return <DocumentStatusBadge status={status} progress={progress} />
  }

  const renderGrid = () => (
    <div className="doc-grid">
      {documents.map(doc => (
        <DocumentCard
          key={doc.doc_id}
          doc={doc}
          deletePending={mutations.deletePending}
          patentPending={mutations.patentPending}
          onOpen={handleOpenDocument}
          onDelete={mutations.requestDelete}
          onPatentAnalyze={(document) => void mutations.handlePatentAnalysis([document])}
          selected={selection.selectedDocumentIds.has(doc.doc_id)}
          onToggleSelect={selection.handleToggleSelect}
          statusBadge={statusBadge}
        />
      ))}
    </div>
  )

  const renderList = () => (
    <div className="doc-list" role="list">
      <div className="doc-list__header" role="presentation">
        <span className="doc-list__col--select" aria-hidden="true" />
        <span className="doc-list__col--icon" aria-hidden="true" />
        <span className="doc-list__col doc-list__col--title">{t('workspace.documents')}</span>
        <span className="doc-list__col doc-list__col--meta">{t('workspace.pages', { count: 0 }).replace('0', '')}</span>
        <span className="doc-list__col doc-list__col--status">{t('doc.actions')}</span>
        <span className="doc-list__col--menu" aria-hidden="true" />
      </div>
      {documents.map(doc => (
        <DocumentRow
          key={doc.doc_id}
          doc={doc}
          deletePending={mutations.deletePending}
          patentPending={mutations.patentPending}
          onOpen={handleOpenDocument}
          onDelete={mutations.requestDelete}
          onPatentAnalyze={(document) => void mutations.handlePatentAnalysis([document])}
          selected={selection.selectedDocumentIds.has(doc.doc_id)}
          onToggleSelect={selection.handleToggleSelect}
          statusBadge={statusBadge}
        />
      ))}
    </div>
  )

  return (
    <motion.div
      className="workspace-page"
      variants={fadeUp}
      initial="hidden"
      animate="visible"
    >
      <section className="workspace-documents">
        <WorkspaceToolbar
          documents={documents}
          viewMode={viewMode}
          onViewChange={setView}
          allDocumentsSelected={selection.allDocumentsSelected}
          selectedDocuments={selection.selectedDocuments}
          onToggleSelectAll={selection.toggleSelectAll}
          onEnqueueSelected={mutations.handleEnqueueSelected}
          onPatentAnalysis={mutations.handlePatentAnalysis}
          onRequestDeleteSelected={mutations.requestDeleteSelected}
          isEnqueueingSelected={mutations.isEnqueueingSelected}
          deletePending={mutations.deletePending}
          patentPending={mutations.patentPending}
          libraryRoot={libraryRoot}
          onImport={importer.handleImport}
          importBusy={importer.busy}
        />
        {importer.uploadProgress !== null && (
          <div className="workspace-upload-progress">
            <ProgressBar
              value={importer.uploadProgress}
              showPercent
              color="var(--accent)"
              height={6}
              label={importer.uploadBatch
                ? t('library.importBatchProgress', importer.uploadBatch)
                : t('library.importing')}
            />
          </div>
        )}
        {processingCount > 0 && (
          <div className="workspace-processing-note">
            <InlineAlert tone="info">
              {t('library.processingNote', { count: processingCount })}
            </InlineAlert>
          </div>
        )}

        <div className="workspace-content">
        {isLoading ? (
          <div className="workspace-skeleton" data-testid="workspace-skeleton" aria-busy="true">
            <div className="workspace-skeleton__title" />
            <div className="doc-grid">
              {Array.from({ length: 6 }, (_, index) => (
                <div key={index} className="workspace-skeleton__card">
                  <Skeleton variant="text" height={16} style={{ width: '72%' }} />
                  <Skeleton variant="text" height={12} style={{ width: '48%' }} />
                  <Skeleton variant="text" height={20} style={{ width: '28%', marginTop: 'auto' }} />
                </div>
              ))}
            </div>
          </div>
        ) : isError ? (
          <div className="workspace-empty">
            <div className="workspace-empty-title">{t('errors.UNKNOWN')}</div>
            <div className="workspace-empty-desc">{t('workspace.loadError')}</div>
            <Button variant="secondary" size="sm" className="workspace-import-btn" onClick={() => window.location.reload()}>
              {t('common.retry')}
            </Button>
          </div>
        ) : documents.length === 0 ? (
          <div className="workspace-empty">
            <PdfIcon size={48} className="workspace-empty-icon" />
            <div className="workspace-empty-title">{t('library.noDocuments')}</div>
            <div className="workspace-empty-desc">
              {processingCount > 0
                ? t('library.processingOnlyHint')
                : t('library.emptyImportHint')}
            </div>
            {processingCount === 0 && (
              <div
                className={`workspace-drop-zone${importer.isDraggingFile ? ' is-dragging' : ''}`}
                onDragEnter={importer.handleDragEnter}
                onDragOver={importer.handleDragOver}
                onDragLeave={importer.handleDragLeave}
                onDrop={importer.handleDrop}
              >
                <PdfIcon size={28} aria-hidden="true" />
                <span>{t('library.emptyImportHint')}</span>
                <Button
                  variant="secondary"
                  size="sm"
                  icon={<PlusIcon size={16} />}
                  className="workspace-import-btn"
                  onClick={importer.handleImport}
                  disabled={importer.busy}
                >
                  {importer.busy
                    ? t('library.importing')
                    : t('library.importPdf')}
                </Button>
              </div>
            )}
          </div>
        ) : (
          viewMode === 'grid' ? renderGrid() : renderList()
        )}
        </div>
      </section>
      <ConfirmDialog
        open={mutations.pendingConfirm !== null}
        title={mutations.confirmDialogTitle}
        message={mutations.confirmDialogMessage}
        confirmLabel={mutations.confirmDialogLabel}
        loading={mutations.deletePending}
        onConfirm={() => { if (mutations.pendingConfirm) void mutations.confirmDocAction(mutations.pendingConfirm) }}
        onCancel={mutations.cancelConfirm}
      />
    </motion.div>
  )
}
