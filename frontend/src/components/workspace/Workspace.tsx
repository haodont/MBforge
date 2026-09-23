import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { motion } from 'framer-motion'
import { fadeUp } from '@/hooks/useAnimations'
import { useAppContext } from '@/context/AppContext'
import {
  useClearDocument,
  useCollections,
  useDeleteDocument,
  useDocuments,
  useEnqueueTask,
  useImportDocument,
  useMoveDocument,
} from '@/api/query/hooks'
import { clearViewerSnapshotsForDoc } from '@/components/project/pdf/viewerSnapshots'
import { showToast } from '@/hooks/useToast'
import { useTranslation } from 'react-i18next'
import {
  FolderIcon,
  GridIcon,
  PdfIcon,
  PlusIcon,
  QueueIcon,
  RefreshCwIcon,
  TableIcon,
  TrashIcon,
} from '@/components/icons'
import LibraryPanel from '@/components/LibraryPanel'
import ConfirmDialog from '@/components/ui/ConfirmDialog'
import Menu, { type MenuActionItem, type MenuItem } from '@/components/ui/Menu'
import IconButton from '@/components/ui/IconButton'
import Button from '@/components/ui/Button'
import Badge from '@/components/ui/Badge'
import ProgressBar from '@/components/ui/ProgressBar'
import Skeleton from '@/components/ui/Skeleton'
import type { DocumentInfo } from '@/api/http/library'
import type { CollectionNode } from '@/api/http/library'
import { AppError, getUserFacingError } from '@/utils/errors'

type ViewMode = 'grid' | 'list'

type DocConfirmAction =
  | { doc: DocumentInfo; action: 'delete' | 'clear' }
  | { docs: DocumentInfo[]; action: 'delete-selected' }

type DocumentActionMenuProps = {
  doc: DocumentInfo
  groups: CollectionNode[]
  groupsError: boolean
  activeCollectionId: string | null
  deletePending: boolean
  movePending: boolean
  onDelete: (doc: DocumentInfo) => void
  onClear: (doc: DocumentInfo) => void
  onMove: (doc: DocumentInfo, targetCollectionId: string | null) => void
}

function DocumentActionMenu({
  doc,
  groups,
  groupsError,
  activeCollectionId,
  deletePending,
  movePending,
  onDelete,
  onClear,
  onMove,
}: DocumentActionMenuProps) {
  const { t } = useTranslation()
  const { libraryRoot } = useAppContext()
  const enqueueMutation = useEnqueueTask()
  const [enqueuePending, setEnqueuePending] = useState(false)

  const handleEnqueue = async () => {
    if (!libraryRoot) return
    setEnqueuePending(true)
    try {
      // Backend resolves file path from document.json; only doc_id is needed.
      await enqueueMutation.mutateAsync({ libraryRoot, filePath: '', docId: doc.doc_id })
      showToast(t('doc.enqueueSuccess', { filename: doc.file_name }), 'success')
    } catch (e) {
      showToast(t('doc.enqueueFailed', { error: getUserFacingError(e, t('common.unknownError')) }), 'error')
    } finally {
      setEnqueuePending(false)
    }
  }

  const moveItems: MenuActionItem[] = groupsError
    ? [{ key: 'groups-error', label: t('workspace.loadGroupsFailed'), disabled: true }]
    : groups.length === 0
      ? [{ key: 'no-groups', label: t('doc.noGroups'), disabled: true }]
      : [
          {
            key: 'move-default',
            label: t('doc.moveToDefault'),
            disabled: movePending || !activeCollectionId,
            onClick: () => onMove(doc, null),
          },
          ...groups.map((group) => {
            const isCurrent = activeCollectionId === group.collection_id
            return {
              key: group.collection_id,
              label: group.name,
              icon: <FolderIcon size={14} />,
              checked: isCurrent,
              disabled: movePending || isCurrent,
              onClick: () => onMove(doc, group.collection_id),
            }
          }),
        ]

  const items: MenuItem[] = [
    {
      key: 'enqueue',
      label: t('doc.enqueue'),
      icon: <FolderIcon size={16} />,
      disabled: enqueuePending,
      onClick: handleEnqueue,
    },
    { type: 'separator', key: 'sep-clear' },
    {
      key: 'clear',
      label: t('doc.clear'),
      icon: <RefreshCwIcon size={16} />,
      disabled: deletePending,
      onClick: () => onClear(doc),
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
    { type: 'separator', key: 'sep-move' },
    { type: 'group', key: 'move-group', label: t('doc.moveToGroup'), items: moveItems },
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
  groups: CollectionNode[]
  groupsError: boolean
  activeCollectionId: string | null
  deletePending: boolean
  movePending: boolean
  onOpen: (doc: DocumentInfo) => void
  onDelete: (doc: DocumentInfo) => void
  onClear: (doc: DocumentInfo) => void
  onMove: (doc: DocumentInfo, targetCollectionId: string | null) => void
  selected: boolean
  onToggleSelect: (doc: DocumentInfo, selected: boolean) => void
  statusBadge: (status: string) => ReactNode
}

function DocumentCard({
  doc,
  groups,
  groupsError,
  activeCollectionId,
  deletePending,
  movePending,
  onOpen,
  onDelete,
  onClear,
  onMove,
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
          groups={groups}
          groupsError={groupsError}
          activeCollectionId={activeCollectionId}
          deletePending={deletePending}
          movePending={movePending}
          onDelete={onDelete}
          onClear={onClear}
          onMove={onMove}
        />
      </div>
      <button
        type="button"
        className="doc-card-open"
        aria-label={doc.title}
        onClick={() => onOpen(doc)}
      >
        <span className="doc-card-icon">
          <PdfIcon size={32} />
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
          {statusBadge(doc.status)}
        </span>
      </button>
    </article>
  )
}

function DocumentRow({
  doc,
  groups,
  groupsError,
  activeCollectionId,
  deletePending,
  movePending,
  onOpen,
  onDelete,
  onClear,
  onMove,
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
        <span className="doc-list__status">{statusBadge(doc.status)}</span>
      </button>
      <div
        className="doc-list__menu"
        onClick={(event) => event.stopPropagation()}
      >
        <DocumentActionMenu
          doc={doc}
          groups={groups}
          groupsError={groupsError}
          activeCollectionId={activeCollectionId}
          deletePending={deletePending}
          movePending={movePending}
          onDelete={onDelete}
          onClear={onClear}
          onMove={onMove}
        />
      </div>
    </div>
  )
}

export default function Workspace() {
  const { t } = useTranslation()
  const {
    libraryRoot,
    activeCollectionId,
    openTab,
  } = useAppContext()
  const { data, isLoading, isError } = useDocuments(activeCollectionId ?? undefined)
  const importMutation = useImportDocument()
  const deleteMutation = useDeleteDocument()
  const bulkEnqueueMutation = useEnqueueTask()
  const clearMutation = useClearDocument()
  const moveMutation = useMoveDocument()
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

  // All available groups, fetched once per mount. Used to populate the
  // "Move to group" sub-menu on every doc-card.
  const { data: groupsData, isError: groupsError } = useCollections()
  const groups = useMemo<CollectionNode[]>(() => groupsData?.collections ?? [], [groupsData])
  const activeGroup = groups.find(group => group.collection_id === activeCollectionId)
  const totalPages = documents.reduce((total, doc) => total + Math.max(0, doc.page_count), 0)
  const selectedDocuments = documents.filter(doc => selectedDocumentIds.has(doc.doc_id))
  const allDocumentsSelected = documents.length > 0 && selectedDocuments.length === documents.length

  useEffect(() => {
    setSelectedDocumentIds(new Set())
  }, [activeCollectionId])

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
    try {
      if (pdfFiles.length > 0) setUploadProgress(0)
      for (const [index, file] of pdfFiles.entries()) {
        setUploadBatch(files.length > 1 ? { current: index + 1, total: pdfFiles.length } : null)
        try {
          await importMutation.mutateAsync({
            file,
            onProgress: (percent) => setUploadProgress(
              Math.round(((completedCount + percent / 100) / pdfFiles.length) * 100),
            ),
          })
          successCount += 1
        } catch (error) {
          const message = error instanceof AppError && error.context?.backend_code === 'duplicate_filename'
            ? t('library.duplicateFilename', { filename: file.name })
            : getUserFacingError(error, t('common.unknownError'))
          failures.push({ file, message })
        }
        completedCount += 1
        setUploadProgress(Math.round((completedCount / pdfFiles.length) * 100))
      }
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
  }, [importMutation, t])

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
      await deleteMutation.mutateAsync(doc.doc_id)
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
    const deletedIds = new Set<string>()
    let failed = 0
    for (const doc of docs) {
      try {
        await deleteMutation.mutateAsync(doc.doc_id)
        deletedIds.add(doc.doc_id)
      } catch {
        failed += 1
      }
    }
    setSelectedDocumentIds(current => {
      const next = new Set(current)
      deletedIds.forEach(docId => next.delete(docId))
      return next
    })
    const deleted = deletedIds.size
    if (failed > 0) {
      showToast(t('workspace.bulkDeletePartial', { deleted, failed }), 'error')
    } else {
      showToast(t('workspace.bulkDeleteSuccess', { count: deleted }), 'success')
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

  const handleClearDocument = useCallback(async (doc: DocumentInfo) => {
    try {
      await clearMutation.mutateAsync(doc.doc_id)
      // 清空会删除该文档全部渲染源；同会话内仍存活的 viewer 快照若不清，
      // 重开 viewer 会把旧 bbox 重新灌回状态。这里同步清除，重开后从空快照
      // 干净重取。
      clearViewerSnapshotsForDoc(doc.doc_id)
      showToast(t('doc.clearSuccess', { filename: doc.file_name }), 'success')
    } catch (e) {
      showToast(t('doc.clearError', { error: getUserFacingError(e, t('common.unknownError')) }), 'error')
    }
  }, [clearMutation, t])

  const confirmDocAction = useCallback(async (target: DocConfirmAction) => {
    setPendingConfirm(null)
    if (target.action === 'delete-selected') await handleDeleteSelected(target.docs)
    else if (target.action === 'delete') await handleDeleteDocument(target.doc)
    else await handleClearDocument(target.doc)
  }, [handleDeleteDocument, handleDeleteSelected, handleClearDocument, setPendingConfirm])

  const pending = pendingConfirm
  const confirmDialogTitle = pending === null ? '' : pending.action === 'clear' ? t('doc.clear') : t('doc.delete')
  const confirmDialogMessage = pending === null ? '' : pending.action === 'delete-selected'
    ? t('workspace.bulkDeleteConfirm', { count: pending.docs.length })
    : pending.action === 'delete'
      ? t('doc.deleteConfirm', { filename: pending.doc.file_name })
      : t('doc.clearConfirm', { filename: pending.doc.file_name })
  const confirmDialogLabel = pending?.action === 'delete-selected'
    ? t('workspace.deleteSelected', { count: pending.docs.length })
    : confirmDialogTitle

  const handleMoveToGroup = useCallback(async (doc: DocumentInfo, targetCollectionId: string | null) => {
    const groupName = targetCollectionId
      ? groups.find(g => g.collection_id === targetCollectionId)?.name ?? ''
      : ''
    try {
      await moveMutation.mutateAsync({
        docId: doc.doc_id,
        fromCollectionId: activeCollectionId ?? null,
        toCollectionId: targetCollectionId,
      })
      if (targetCollectionId) {
        showToast(t('doc.moveSuccess', { filename: doc.file_name, name: groupName }), 'success')
      } else {
        showToast(t('doc.moveUnassigned', { filename: doc.file_name }), 'success')
      }
    } catch (e) {
      showToast(t('doc.moveError', { error: getUserFacingError(e, t('common.unknownError')) }), 'error')
    }
  }, [moveMutation, groups, activeCollectionId, t])

  const statusBadge = (status: string) => {
    const displayStatus = status === 'indexing' ? 'pending' : status
    const tone = displayStatus === 'ready' ? 'success' : displayStatus === 'error' ? 'danger' : 'warning'
    const cls = displayStatus === 'ready' ? 'badge-ready' :
                displayStatus === 'error' ? 'badge-error' : 'badge-pending'
    return <Badge tone={tone} className={`doc-status-badge ${cls}`}>{displayStatus}</Badge>
  }

  // Build a name lookup once per render for the "Move to group" menu.
  // Reserved for future per-group badge copy; the inline menu already
  // reads ``group.name`` directly, so the lookup is currently unused.
  // const groupNameById = useMemo(() => {
  //   const map = new Map<string, string>()
  //   for (const group of groups) {
  //     map.set(group.collection_id, group.name)
  //   }
  //   return map
  // }, [groups])

  const renderGrid = () => (
    <div className="doc-grid">
      {documents.map(doc => (
        <DocumentCard
          key={doc.doc_id}
          doc={doc}
          groups={groups}
          groupsError={groupsError}
          activeCollectionId={activeCollectionId}
          deletePending={deleteMutation.isPending}
          movePending={moveMutation.isPending}
          onOpen={handleOpenDocument}
          onDelete={(document) => setPendingConfirm({ doc: document, action: 'delete' })}
          onClear={(document) => setPendingConfirm({ doc: document, action: 'clear' })}
          onMove={(document, target) => void handleMoveToGroup(document, target)}
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
          groups={groups}
          groupsError={groupsError}
          activeCollectionId={activeCollectionId}
          deletePending={deleteMutation.isPending}
          movePending={moveMutation.isPending}
          onOpen={handleOpenDocument}
          onDelete={(document) => setPendingConfirm({ doc: document, action: 'delete' })}
          onClear={(document) => setPendingConfirm({ doc: document, action: 'clear' })}
          onMove={(document, target) => void handleMoveToGroup(document, target)}
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
      <aside
        className="workspace-library"
        aria-label={t('library.title')}
      >
        <LibraryPanel />
      </aside>
      <section className="workspace-documents">
        <div className="workspace-toolbar">
          <div className="workspace-summary" aria-label={t('workspace.summary')}>
            <span>{t('workspace.documentCount', { count: documents.length })}</span>
            <span>{t('workspace.pageCount', { count: totalPages })}</span>
            <span className="workspace-summary__group">
              {activeGroup?.name ?? t('library.allDocuments')}
            </span>
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
              {activeCollectionId
                ? t('library.emptyCollection')
                : t('library.emptyImportHint')}
            </div>
            {!activeCollectionId && (
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
        loading={deleteMutation.isPending || clearMutation.isPending}
        onConfirm={() => { if (pendingConfirm) void confirmDocAction(pendingConfirm) }}
        onCancel={() => setPendingConfirm(null)}
      />
    </motion.div>
  )
}
