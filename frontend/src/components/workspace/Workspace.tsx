import { useCallback, useMemo, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { motion } from 'framer-motion'
import { fadeUp } from '@/hooks/useAnimations'
import { useAppContext } from '@/context/AppContext'
import {
  useDeleteDocuments,
  useDocuments,
  useEnqueueTask,
  useImportDocument,
  useIngestQueue,
  usePatentAnalysis,
} from '@/api/query/hooks'
import { queryKeys } from '@/api/query/keys'
import { showToast } from '@/hooks/useToast'
import { useTranslation } from 'react-i18next'
import {
  FlaskIcon,
  FolderIcon,
  GridIcon,
  PdfIcon,
  PlusIcon,
  QueueIcon,
  TableIcon,
  TrashIcon,
} from '@/components/icons'
import ConfirmDialog from '@/components/ui/ConfirmDialog'
import InlineAlert from '@/components/ui/InlineAlert'
import Menu, { type MenuItem } from '@/components/ui/Menu'
import IconButton from '@/components/ui/IconButton'
import Button from '@/components/ui/Button'
import Badge from '@/components/ui/Badge'
import ProgressBar from '@/components/ui/ProgressBar'
import Skeleton from '@/components/ui/Skeleton'
import type { DocumentInfo } from '@/api/http/library'
import type { IngestTask } from '@/api/http/ingest_queue'
import { AppError, getUserFacingError } from '@/utils/errors'

type ViewMode = 'grid' | 'list'

type DocConfirmAction =
  | { doc: DocumentInfo; action: 'delete' }
  | { docs: DocumentInfo[]; action: 'delete-selected' }

/** Workspace status badge presentation, keyed by the status we display. */
const DOC_STATUS_META: Record<
  string,
  { tone: 'success' | 'warning' | 'danger' | 'info' | 'neutral'; cls: string; labelKey: string }
> = {
  pending: { tone: 'warning', cls: 'badge-pending', labelKey: 'workspace.statusPending' },
  processing: { tone: 'info', cls: 'badge-processing', labelKey: 'workspace.statusProcessing' },
  ready: { tone: 'success', cls: 'badge-ready', labelKey: 'workspace.statusReady' },
  error: { tone: 'danger', cls: 'badge-error', labelKey: 'workspace.statusError' },
  extracted: { tone: 'neutral', cls: 'badge-extracted', labelKey: 'workspace.statusExtracted' },
}

/** Queue status priority, mirroring the queue page's ordering. */
const QUEUE_STATUS_RANK: Record<IngestTask['status'], number> = {
  processing: 0,
  pending: 1,
  failed: 2,
  cancelled: 3,
  done: 4,
}

/** Keep the most relevant queue row per document for status overlay. */
function buildQueueByDoc(tasks: IngestTask[]): Map<string, IngestTask> {
  const byDoc = new Map<string, IngestTask>()
  for (const task of tasks) {
    if (!task.doc_id) continue
    const current = byDoc.get(task.doc_id)
    if (!current || QUEUE_STATUS_RANK[task.status] < QUEUE_STATUS_RANK[current.status]) {
      byDoc.set(task.doc_id, task)
    }
  }
  return byDoc
}

/** Percent of a run's stages that finished successfully (null when unknown). */
function queueProgress(task: IngestTask | undefined): number | null {
  if (!task) return null
  const statuses = Object.values(task.stage_statuses)
  if (statuses.length === 0) return null
  const done = statuses.filter((status) => status === 'success').length
  return Math.round((done / statuses.length) * 100)
}

type DocumentActionMenuProps = {
  doc: DocumentInfo
  deletePending: boolean
  patentPending: boolean
  onDelete: (doc: DocumentInfo) => void
  onPatentAnalyze: (doc: DocumentInfo) => void
}

function DocumentActionMenu({
  doc,
  deletePending,
  patentPending,
  onDelete,
  onPatentAnalyze,
}: DocumentActionMenuProps) {
  const { t } = useTranslation()
  const { libraryRoot } = useAppContext()
  const enqueueMutation = useEnqueueTask()
  const [enqueuePending, setEnqueuePending] = useState(false)

  const handleEnqueue = async () => {
    if (!libraryRoot) return
    setEnqueuePending(true)
    try {
      // Backend resolves the file path from the document registry; only doc_id is needed.
      await enqueueMutation.mutateAsync({ libraryRoot, filePath: '', docId: doc.doc_id })
      showToast(t('doc.enqueueSuccess', { filename: doc.file_name }), 'success')
    } catch (e) {
      showToast(t('doc.enqueueFailed', { error: getUserFacingError(e, t('common.unknownError')) }), 'error')
    } finally {
      setEnqueuePending(false)
    }
  }

  const items: MenuItem[] = [
    {
      key: 'enqueue',
      label: t('doc.enqueue'),
      icon: <FolderIcon size={16} />,
      disabled: enqueuePending,
      onClick: handleEnqueue,
    },
    {
      key: 'patent-analysis',
      label: t('doc.patentAnalysis'),
      icon: <FlaskIcon size={16} />,
      disabled: patentPending,
      onClick: () => onPatentAnalyze(doc),
    },
    { type: 'separator', key: 'sep-delete' },
    {
      key: 'delete',
      label: t('doc.delete'),
      icon: <TrashIcon size={16} />,
      danger: true,
      disabled: deletePending,
      onClick: () => onDelete(doc),
    },
  ]

  return (
    <Menu
      align="right"
      items={items}
      trigger={(toggle) => (
        <IconButton
          size={32}
          ariaLabel={t('doc.actions')}
          title={t('doc.actions')}
          onClick={(event) => {
            event.stopPropagation()
            toggle()
          }}
        >
          ⋯
        </IconButton>
      )}
    />
  )
}

type DocumentItemProps = {
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

function DocumentCard({
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

function DocumentRow({
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

/** PDFs uploaded at once; more only queue on the server's per-library lock. */
const UPLOAD_CONCURRENCY = 3

/** Run `worker` over `items` with at most `limit` calls in flight at a time. */
async function runWithConcurrency<T>(
  items: readonly T[],
  limit: number,
  worker: (item: T, index: number) => Promise<void>,
): Promise<void> {
  let next = 0
  const runners = Array.from(
    { length: Math.max(1, Math.min(limit, items.length)) },
    async () => {
      while (next < items.length) {
        const index = next
        next += 1
        await worker(items[index], index)
      }
    },
  )
  await Promise.all(runners)
}

export default function Workspace() {
  const { t } = useTranslation()
  const {
    libraryRoot,
    openTab,
  } = useAppContext()
  const { data, isLoading, isError } = useDocuments()
  const queryClient = useQueryClient()
  const importMutation = useImportDocument()
  const deleteMutation = useDeleteDocuments()
  const bulkEnqueueMutation = useEnqueueTask()
  const patentMutation = usePatentAnalysis()
  // Documents under processing are deliberately absent from the listing, so
  // the queue is what tells the user their import is being worked on. The queue
  // holds one row per stage per run, so count distinct documents (a retry can
  // leave more than one row of a run active at once).
  const { data: queueTasks = [] } = useIngestQueue(libraryRoot)
  const processingCount = useMemo(() => {
    const docIds = new Set<string>()
    for (const task of queueTasks) {
      if (task.doc_id && (task.status === 'pending' || task.status === 'processing')) {
        docIds.add(task.doc_id)
      }
    }
    return docIds.size
  }, [queueTasks])
  const queueByDoc = useMemo(() => buildQueueByDoc(queueTasks), [queueTasks])
  const documents = data?.documents ?? []
  const [selectedDocumentIds, setSelectedDocumentIds] = useState<Set<string>>(() => new Set())
  const [isDraggingFile, setIsDraggingFile] = useState(false)
  const [uploadProgress, setUploadProgress] = useState<number | null>(null)
  const [uploadBatch, setUploadBatch] = useState<{ current: number; total: number } | null>(null)
  const [isImporting, setIsImporting] = useState(false)
  const [isEnqueueingSelected, setIsEnqueueingSelected] = useState(false)
  const importInProgressRef = useRef(false)
  const enqueueSelectedInProgressRef = useRef(false)
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

  const totalPages = documents.reduce((total, doc) => total + Math.max(0, doc.page_count), 0)
  const selectedDocuments = documents.filter(doc => selectedDocumentIds.has(doc.doc_id))
  const allDocumentsSelected = documents.length > 0 && selectedDocuments.length === documents.length

  const handleToggleSelect = useCallback((doc: DocumentInfo, selected: boolean) => {
    setSelectedDocumentIds(current => {
      const next = new Set(current)
      if (selected) next.add(doc.doc_id)
      else next.delete(doc.doc_id)
      return next
    })
  }, [])

  const handleImportFiles = useCallback(async (fileList: FileList | File[]) => {
    const files = Array.from(fileList)
    if (files.length === 0 || importInProgressRef.current) return

    const isPdfFile = (file: File) =>
      file.type === 'application/pdf' || file.name.toLowerCase().endsWith('.pdf')
    const failures = files
      .filter(file => !isPdfFile(file))
      .map(file => ({ file, message: t('library.pdfFilesOnly') }))
    const pdfFiles = files.filter(isPdfFile)

    if (files.length === 1 && pdfFiles.length === 0) {
      showToast(t('library.importError', { error: failures[0].message }), 'error')
      return
    }

    importInProgressRef.current = true
    setIsImporting(true)
    let successCount = 0
    let completedCount = 0
    // One fraction per file: the aggregate bar is their mean, so one file
    // finishing while another is mid-flight cannot make the bar jump back.
    const perFileProgress = pdfFiles.map(() => 0)
    const publishProgress = () => {
      const total = perFileProgress.reduce((sum, value) => sum + value, 0)
      setUploadProgress(Math.round((total / pdfFiles.length) * 100))
    }
    try {
      if (pdfFiles.length > 0) setUploadProgress(0)
      if (files.length > 1) setUploadBatch({ current: 0, total: pdfFiles.length })
      await runWithConcurrency(pdfFiles, UPLOAD_CONCURRENCY, async (file, index) => {
        try {
          await importMutation.mutateAsync({
            file,
            onProgress: (percent) => {
              perFileProgress[index] = percent / 100
              publishProgress()
            },
          })
          successCount += 1
        } catch (error) {
          const message = error instanceof AppError && error.context?.backend_code === 'duplicate_filename'
            ? t('library.duplicateFilename', { filename: file.name })
            : getUserFacingError(error, t('common.unknownError'))
          failures.push({ file, message })
        }
        completedCount += 1
        perFileProgress[index] = 1
        publishProgress()
        if (files.length > 1) setUploadBatch({ current: completedCount, total: pdfFiles.length })
      })
      // One refetch for the whole batch, instead of one per uploaded file.
      void queryClient.invalidateQueries({ queryKey: queryKeys.documents.all })
      void queryClient.invalidateQueries({ queryKey: queryKeys.ingest.all })
    } finally {
      importInProgressRef.current = false
      setIsImporting(false)
      setUploadProgress(null)
      setUploadBatch(null)
    }

    if (files.length === 1) {
      if (failures.length > 0) {
        showToast(t('library.importError', { error: failures[0].message }), 'error')
      } else {
        showToast(t('library.importSuccess'), 'success')
      }
    } else if (failures.length > 0) {
      const firstFailure = failures[0]
      showToast(t('library.importBatchPartial', {
        success: successCount,
        failed: failures.length,
        error: `${firstFailure.file.name}: ${firstFailure.message}`,
      }), 'error')
    } else {
      showToast(t('library.importBatchSuccess', { count: successCount }), 'success')
    }
  }, [importMutation, queryClient, t])

  const handleImport = useCallback(() => {
    const input = document.createElement('input')
    input.type = 'file'
    input.accept = '.pdf,application/pdf'
    input.multiple = true
    input.onchange = () => {
      if (input.files?.length) void handleImportFiles(input.files)
    }
    input.click()
  }, [handleImportFiles])

  const handleDrop = useCallback((event: React.DragEvent<HTMLDivElement>) => {
    event.preventDefault()
    setIsDraggingFile(false)
    void handleImportFiles(event.dataTransfer.files)
  }, [handleImportFiles])

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

  const [pendingConfirm, setPendingConfirm] = useState<DocConfirmAction | null>(null)

  const handleDeleteDocument = useCallback(async (doc: DocumentInfo) => {
    try {
      await deleteMutation.mutateAsync([doc.doc_id])
      setSelectedDocumentIds(current => {
        if (!current.has(doc.doc_id)) return current
        const next = new Set(current)
        next.delete(doc.doc_id)
        return next
      })
      showToast(t('doc.deleteSuccess', { filename: doc.file_name }), 'success')
    } catch (e) {
      showToast(t('doc.deleteError', { error: getUserFacingError(e, t('common.unknownError')) }), 'error')
    }
  }, [deleteMutation, t])

  const handleDeleteSelected = useCallback(async (docs: DocumentInfo[]) => {
    const docIds = docs.map((doc) => doc.doc_id)
    try {
      await deleteMutation.mutateAsync(docIds)
      setSelectedDocumentIds(current => {
        const next = new Set(current)
        docIds.forEach(docId => next.delete(docId))
        return next
      })
      showToast(t('workspace.bulkDeleteSuccess', { count: docIds.length }), 'success')
    } catch (e) {
      showToast(t('workspace.bulkDeleteError', { error: getUserFacingError(e, t('common.unknownError')) }), 'error')
    }
  }, [deleteMutation, t])

  const handleEnqueueSelected = async (docs: DocumentInfo[]) => {
    if (!libraryRoot || docs.length === 0 || enqueueSelectedInProgressRef.current) return
    enqueueSelectedInProgressRef.current = true
    setIsEnqueueingSelected(true)
    const queuedIds = new Set<string>()
    const failures: { doc: DocumentInfo; message: string }[] = []
    try {
      for (const doc of docs) {
        try {
          await bulkEnqueueMutation.mutateAsync({
            libraryRoot,
            filePath: '',
            docId: doc.doc_id,
          })
          queuedIds.add(doc.doc_id)
        } catch (error) {
          failures.push({
            doc,
            message: getUserFacingError(error, t('common.unknownError')),
          })
        }
      }
    } finally {
      enqueueSelectedInProgressRef.current = false
      setIsEnqueueingSelected(false)
    }
    setSelectedDocumentIds(current => {
      const next = new Set(current)
      queuedIds.forEach(docId => next.delete(docId))
      return next
    })
    if (failures.length > 0) {
      const firstFailure = failures[0]
      showToast(t('workspace.bulkEnqueuePartial', {
        queued: queuedIds.size,
        failed: failures.length,
        filename: firstFailure.doc.file_name,
        error: firstFailure.message,
      }), 'error')
    } else {
      showToast(t('workspace.bulkEnqueueSuccess', { count: queuedIds.size }), 'success')
    }
  }

  // Patent analysis is decoupled from import: the document is extensible as
  // soon as it is extracted, and this queues a Patent-only run for each target.
  const handlePatentAnalysis = useCallback(async (docs: DocumentInfo[]) => {
    const docIds = docs.map((doc) => doc.doc_id)
    if (docIds.length === 0) return
    try {
      const result = await patentMutation.mutateAsync(docIds)
      showToast(t('workspace.patentAnalysisSuccess', { count: result.enqueued }), 'success')
    } catch (e) {
      showToast(t('workspace.patentAnalysisError', { error: getUserFacingError(e, t('common.unknownError')) }), 'error')
    }
  }, [patentMutation, t])

  const confirmDocAction = useCallback(async (target: DocConfirmAction) => {
    setPendingConfirm(null)
    if (target.action === 'delete-selected') await handleDeleteSelected(target.docs)
    else await handleDeleteDocument(target.doc)
  }, [handleDeleteDocument, handleDeleteSelected, setPendingConfirm])

  const pending = pendingConfirm
  const confirmDialogTitle = pending === null ? '' : t('doc.delete')
  const confirmDialogMessage = pending === null ? '' : pending.action === 'delete-selected'
    ? t('workspace.bulkDeleteConfirm', { count: pending.docs.length })
    : t('doc.deleteConfirm', { filename: pending.doc.file_name })
  const confirmDialogLabel = pending?.action === 'delete-selected'
    ? t('workspace.deleteSelected', { count: pending.docs.length })
    : confirmDialogTitle

  const statusBadge = (doc: DocumentInfo) => {
    const task = queueByDoc.get(doc.doc_id)
    // A live queue row ("pending"/"processing") reflects the run in progress;
    // otherwise fall back to the document's resting status.
    const status =
      task && (task.status === 'processing' || task.status === 'pending')
        ? task.status
        : doc.status === 'indexing'
          ? 'pending'
          : doc.status
    const meta = DOC_STATUS_META[status] ?? DOC_STATUS_META.pending
    const progress = task && task.status === 'processing' ? queueProgress(task) : null
    return (
      <span className="doc-status">
        <Badge tone={meta.tone} className={`doc-status-badge ${meta.cls}`}>
          {t(meta.labelKey)}
        </Badge>
        {progress !== null && (
          <span
            className="doc-status-progress"
            aria-label={t('workspace.processingProgress', { percent: progress })}
          >
            <span className="doc-status-progress__bar" aria-hidden>
              <span
                className="doc-status-progress__fill"
                style={{ width: `${progress}%` }}
              />
            </span>
            {progress}%
          </span>
        )}
      </span>
    )
  }

  const renderGrid = () => (
    <div className="doc-grid">
      {documents.map(doc => (
        <DocumentCard
          key={doc.doc_id}
          doc={doc}
          deletePending={deleteMutation.isPending}
          patentPending={patentMutation.isPending}
          onOpen={handleOpenDocument}
          onDelete={(document) => setPendingConfirm({ doc: document, action: 'delete' })}
          onPatentAnalyze={(document) => void handlePatentAnalysis([document])}
          selected={selectedDocumentIds.has(doc.doc_id)}
          onToggleSelect={handleToggleSelect}
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
          deletePending={deleteMutation.isPending}
          patentPending={patentMutation.isPending}
          onOpen={handleOpenDocument}
          onDelete={(document) => setPendingConfirm({ doc: document, action: 'delete' })}
          onPatentAnalyze={(document) => void handlePatentAnalysis([document])}
          selected={selectedDocumentIds.has(doc.doc_id)}
          onToggleSelect={handleToggleSelect}
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
                  onClick={() => setSelectedDocumentIds(allDocumentsSelected
                    ? new Set()
                    : new Set(documents.map(doc => doc.doc_id)))}
                  disabled={deleteMutation.isPending || isEnqueueingSelected}
                >
                  {allDocumentsSelected ? t('workspace.deselectAll') : t('workspace.selectAll')}
                </Button>
                {selectedDocuments.length > 0 && (
                  <Button
                    variant="secondary"
                    size="sm"
                    icon={<QueueIcon size={16} />}
                    onClick={() => void handleEnqueueSelected(selectedDocuments)}
                    disabled={deleteMutation.isPending || isEnqueueingSelected || !libraryRoot}
                  >
                    {isEnqueueingSelected
                      ? t('workspace.enqueueingSelected')
                      : t('workspace.enqueueSelected', { count: selectedDocuments.length })}
                  </Button>
                )}
                {selectedDocuments.length > 0 && (
                  <Button
                    variant="secondary"
                    size="sm"
                    icon={<FlaskIcon size={16} />}
                    onClick={() => void handlePatentAnalysis(selectedDocuments)}
                    disabled={deleteMutation.isPending || patentMutation.isPending}
                  >
                    {patentMutation.isPending
                      ? t('workspace.patentAnalyzingSelected')
                      : t('workspace.patentAnalysisSelected', { count: selectedDocuments.length })}
                  </Button>
                )}
                {selectedDocuments.length > 0 && (
                  <Button
                    variant="danger"
                    size="sm"
                    icon={<TrashIcon size={16} />}
                    onClick={() => setPendingConfirm({ docs: selectedDocuments, action: 'delete-selected' })}
                    disabled={deleteMutation.isPending || isEnqueueingSelected}
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
                onClick={() => setView('grid')}
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
                onClick={() => setView('list')}
              >
                <TableIcon size={16} />
              </Button>
            </div>
            <Button
              variant="secondary"
              size="sm"
              icon={<PlusIcon size={16} />}
              className="workspace-import-btn"
              onClick={handleImport}
              disabled={isImporting || importMutation.isPending}
            >
              {isImporting || importMutation.isPending ? t('library.importing') : t('library.importPdf')}
            </Button>
          </div>
        </div>
        {uploadProgress !== null && (
          <div className="workspace-upload-progress">
            <ProgressBar
              value={uploadProgress}
              showPercent
              color="var(--accent)"
              height={6}
              label={uploadBatch
                ? t('library.importBatchProgress', uploadBatch)
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
                className={`workspace-drop-zone${isDraggingFile ? ' is-dragging' : ''}`}
                onDragEnter={(event) => {
                  event.preventDefault()
                  setIsDraggingFile(true)
                }}
                onDragOver={(event) => event.preventDefault()}
                onDragLeave={() => setIsDraggingFile(false)}
                onDrop={handleDrop}
              >
                <PdfIcon size={28} aria-hidden="true" />
                <span>{t('library.emptyImportHint')}</span>
                <Button
                  variant="secondary"
                  size="sm"
                  icon={<PlusIcon size={16} />}
                  className="workspace-import-btn"
                  onClick={handleImport}
                  disabled={isImporting || importMutation.isPending}
                >
                  {isImporting || importMutation.isPending
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
        open={pendingConfirm !== null}
        title={confirmDialogTitle}
        message={confirmDialogMessage}
        confirmLabel={confirmDialogLabel}
        loading={deleteMutation.isPending}
        onConfirm={() => { if (pendingConfirm) void confirmDocAction(pendingConfirm) }}
        onCancel={() => setPendingConfirm(null)}
      />
    </motion.div>
  )
}
