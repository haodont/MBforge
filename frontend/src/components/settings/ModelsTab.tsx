import { useState, useCallback, useEffect, useMemo, useRef } from 'react'
import { useTranslation } from 'react-i18next'
import { type DownloadProgress } from '@/api/http/download'
import {
  useModels,
  useModelsCacheDirInfo,
  useRefreshResolvedPaths,
  useDeleteModel,
  useTestModel,
  useDownloadModel,
  useDownloadModelSubfile,
} from '@/api/query/hooks'
import ModelCard from '@/components/settings/ModelCard'
import Button from '@/components/ui/Button'
import { showToast } from '@/hooks/useToast'
import { getUserFacingError } from '@/utils/errors'

export interface DownloadState {
  [modelId: string]: {
    progress: number
    status: string
    error?: string
    source?: string
    fileName?: string
    fileIndex?: number
    totalFiles?: number
  } | undefined
}

export default function ModelsTab() {
  const { t } = useTranslation()
  const [downloadState, setDownloadState] = useState<DownloadState>({})
  const [deleteConfirm, setDeleteConfirm] = useState<string | null>(null)
  const [customOpen, setCustomOpen] = useState(false)
  const [abortMap, setAbortMap] = useState<Map<string, () => void>>(new Map())
  const [testingSubfiles, setTestingSubfiles] = useState<Set<string>>(new Set())

  const {
    data: modelsData,
    isFetching: modelsFetching,
    refetch: refetchModels,
  } = useModels()
  const {
    data: cacheDirData,
    isError: cacheDirIsError,
    error: cacheDirError,
  } = useModelsCacheDirInfo()
  const { mutateAsync: refreshPaths } = useRefreshResolvedPaths()
  const { mutateAsync: deleteModelAsync } = useDeleteModel()
  const { mutateAsync: testModelAsync } = useTestModel()
  const { mutateAsync: downloadModelAsync } = useDownloadModel()
  const { mutateAsync: downloadSubfileAsync } = useDownloadModelSubfile()

  const models = useMemo(() => modelsData?.models ?? [], [modelsData])
  const cacheDir = cacheDirData?.mbforge.path ?? ''
  const refreshing = modelsFetching
  const didInitRefresh = useRef(false)

  // Ask Rust to rescan ~/mbforge/ and refresh resolved_paths.json once on
  // mount, so the Python side sees newly placed files on its next read.
  useEffect(() => {
    if (didInitRefresh.current) return
    didInitRefresh.current = true
    void refreshPaths().catch(() => console.warn('refreshResolvedPaths failed'))
  }, [refreshPaths])

  useEffect(() => {
    if (!cacheDirIsError) return
    showToast(t('models.cacheDirFailed') + ': ' + getUserFacingError(cacheDirError), 'error')
  }, [cacheDirIsError, cacheDirError, t])

  const manualRefresh = useCallback(async () => {
    await refreshPaths().catch(() => console.warn('refreshResolvedPaths failed'))
    const { data: resp } = await refetchModels()
    if (resp?.success) {
      // Silent by default; only explicit refresh toasts (avoids duplicate
      // prompts on initial mount / after add-remove).
      const ready = resp.models.filter(m => m.downloaded).length
      showToast(t('models.detectComplete', { ready, total: resp.models.length }), 'success')
    } else {
      showToast(resp?.error || t('models.loadFailed'), 'error')
    }
  }, [refreshPaths, refetchModels, t])

  const handleDownload = useCallback((modelId: string) => {
    setDownloadState(prev => {
      const current = prev[modelId]
      if (current?.status === 'downloading' || current?.status === 'connecting') return prev
      return {
        ...prev,
        [modelId]: { progress: 0, status: 'connecting' },
      }
    })

    void downloadModelAsync({
      resourceId: modelId,
      onProgress: (event: DownloadProgress) => {
        setDownloadState(prev => {
          const current = prev[modelId] ?? { progress: 0, status: 'idle' }
          switch (event.status) {
            case 'connecting':
              return { ...prev, [modelId]: { ...current, status: 'connecting' } }
            case 'downloading': {
              const progress = event.total_files > 0
                ? Math.round(((event.file_index) * 100 / event.total_files) + (event.file_progress * 100 / event.total_files))
                : current.progress
              return {
                ...prev,
                [modelId]: {
                  ...current,
                  status: 'downloading',
                  progress,
                  fileName: event.file,
                  fileIndex: event.file_index,
                  totalFiles: event.total_files,
                },
              }
            }
            case 'completed':
              return { ...prev, [modelId]: { progress: 100, status: 'completed' } }
            case 'failed':
              return { ...prev, [modelId]: { ...current, status: 'failed', error: event.error } }
            default:
              return prev
          }
        })
      },
      onCancelReady: cancel => {
        setAbortMap(prev => {
          const next = new Map(prev)
          next.set(modelId, cancel)
          return next
        })
      },
    })
  }, [downloadModelAsync])

  const handleCancel = useCallback((modelId: string) => {
    abortMap.get(modelId)?.()
    setAbortMap(prev => {
      const next = new Map(prev)
      next.delete(modelId)
      return next
    })
    setDownloadState(prev => ({ ...prev, [modelId]: { progress: 0, status: 'idle' } }))
  }, [abortMap])

  const handleDelete = useCallback(async (modelId: string) => {
    try {
      await deleteModelAsync(modelId)
      setDeleteConfirm(null)
    } catch (e) {
      showToast(t('models.deleteError', { error: getUserFacingError(e) }), 'error')
    }
  }, [deleteModelAsync, t])

  // ─── Multi-file sub-resource actions (key: `${modelId}::${subpath}`) ───
  const handleDownloadSubfile = useCallback((modelId: string, subpath: string) => {
    const key = `${modelId}::${subpath}`
    setDownloadState(prev => ({
      ...prev,
      [key]: { progress: 0, status: 'connecting' },
    }))
    void downloadSubfileAsync({
      resourceId: modelId,
      subpath,
      onProgress: (event: DownloadProgress) => {
        setDownloadState(prev => {
          const current = prev[key] ?? { progress: 0, status: 'idle' }
          if (event.status === 'completed') {
            return { ...prev, [key]: { progress: 100, status: 'completed' } }
          }
          if (event.status === 'failed') {
            return { ...prev, [key]: { ...current, status: 'failed', error: event.error } }
          }
          return { ...prev, [key]: { ...current, status: event.status } }
        })
      },
      onCancelReady: cancel => {
        setAbortMap(prev => {
          const next = new Map(prev)
          next.set(key, cancel)
          return next
        })
      },
    })
  }, [downloadSubfileAsync])

  // ─── Model test ───
  // Card-level Test: single-file tests directly; multi-file tests the first
  // subfile (most commonly the doc).
  const handleTest = useCallback(async (modelId: string, subpath?: string) => {
    // Multi-file model: when subpath is not given, test the first subfile
    // (catalog order, usually the doc).
    if (subpath === undefined) {
      const m = models.find(x => x.id === modelId)
      if (m?.subfiles && m.subfiles.length > 0) {
        subpath = m.subfiles[0].relpath
      }
    }
    const key = subpath ? `${modelId}::${subpath}` : `${modelId}::`
    setTestingSubfiles(prev => {
      const next = new Set(prev)
      next.add(key)
      return next
    })
    try {
      const result = await testModelAsync({ resourceId: modelId, subpath })
      if (result.ok) {
        showToast(t('models.testOk', { ms: result.duration_ms }), 'success')
      } else {
        showToast(t('models.testFailed', { error: result.error || t('models.unknownError') }), 'error')
      }
    } catch (e) {
      showToast(t('models.testFailed', { error: getUserFacingError(e) }), 'error')
    } finally {
      setTestingSubfiles(prev => {
        const next = new Set(prev)
        next.delete(key)
        return next
      })
    }
  }, [t, models, testModelAsync])

  // Group by type (order preserved: embedding → reranker → detection)
  const typeOrder: Array<{ key: string; labelKey: string }> = [
    { key: 'embedding', labelKey: 'models.embedding' },
    { key: 'reranker', labelKey: 'models.reranker' },
    { key: 'detection', labelKey: 'models.detection' },
  ]

  const readyCount = models.filter(m => m.downloaded).length
  const totalCount = models.length

  return (
    <div className="settings-section">
      <div className="settings-group">
        {/* Path hint: users should place model files under cacheDir — prominent */}
        {cacheDir && (
          <div className="models-path-hint">
            <div className="models-path-hint-label">{t('models.pathHint')}</div>
            <code className="models-path-hint-path">{cacheDir}</code>
          </div>
        )}

        {/* Summary + refresh (compact row) */}
        <div className="models-header">
          <span className="models-header-count">
            {t('models.readyCount', { ready: readyCount, total: totalCount })}
          </span>
          <Button
            size="sm"
            variant="ghost"
            onClick={manualRefresh}
            disabled={refreshing}
            title={t('models.refresh')}
          >
            {refreshing ? '⟳' : '↻'} {t('models.refresh')}
          </Button>
        </div>

        {models.length === 0 ? (
          <div className="settings-empty-state">
            {t('models.serverNotStarted')}
          </div>
        ) : (
          typeOrder.map(({ key, labelKey }) => {
            const group = models.filter(m => m.type === key)
            if (group.length === 0) return null
            const groupReady = group.filter(m => m.downloaded).length
            return (
              <div key={key} className="settings-model-group">
                <div className="settings-model-group-label">
                  <span>{t(labelKey)}</span>
                  <span className="settings-model-group-count">{groupReady} / {group.length}</span>
                </div>
                <div className="settings-model-list">
                  {group.map(model => {
                    // Multi-file model: pull sub-file states out of downloadState
                    const subfileStates: Record<string, DownloadState[string]> = {}
                    if (model.subfiles.length > 0) {
                      for (const sf of model.subfiles) {
                        const key = `${model.id}::${sf.relpath}`
                        if (downloadState[key]) subfileStates[sf.relpath] = downloadState[key]
                      }
                    }
                    return (
                      <ModelCard
                        key={model.id}
                        model={model}
                        state={downloadState[model.id]}
                        deleteConfirm={deleteConfirm}
                        onDownload={() => handleDownload(model.id)}
                        onCancel={() => handleCancel(model.id)}
                        onDelete={() => setDeleteConfirm(model.id)}
                        onConfirmDelete={() => handleDelete(model.id)}
                        onCancelDelete={() => setDeleteConfirm(null)}
                        onDownloadSubfile={subpath => handleDownloadSubfile(model.id, subpath)}
                        onTest={subpath => handleTest(model.id, subpath)}
                        subfileStates={subfileStates}
                        testingSubfiles={new Set(
                          [...testingSubfiles].filter(k => k.startsWith(`${model.id}::`))
                        )}
                      />
                    )
                  })}
                </div>
              </div>
            )
          })
        )}

        {/* Custom model hint (collapsible) */}
        <details className="settings-custom-hint" open={customOpen} onToggle={e => setCustomOpen((e.target as HTMLDetailsElement).open)}>
          <summary className="settings-custom-hint-title">{t('models.customTitle')}</summary>
          <div className="settings-custom-hint-body">
            <div>{t('models.customDesc')}</div>
            <div className="settings-custom-hint-code">{t('models.customHint')}</div>
          </div>
        </details>
      </div>
    </div>
  )
}
