/** React Query hooks for model downloads + resource management. */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  listModels,
  downloadModel,
  downloadModelSubfile,
  deleteModel,
  testModel,
  type DownloadProgress,
  type ModelTestResult,
} from '@/api/http/download'
import { refreshResolvedPaths, modelsCacheDirInfo } from '@/api/http/environment'
import { queryKeys } from '../keys'

/** List the resource catalog with each model's live status. */
export function useModels() {
  return useQuery({
    queryKey: queryKeys.models.list(),
    queryFn: listModels,
  })
}

/** Model cache directory metadata (mbforge / huggingface / modelscope). */
export function useModelsCacheDirInfo() {
  return useQuery({
    queryKey: queryKeys.models.cacheDir(),
    queryFn: modelsCacheDirInfo,
  })
}

/** Rescan the cache directory and rewrite `resolved_paths.json`. */
export function useRefreshResolvedPaths() {
  const qc = useQueryClient()

  return useMutation({
    mutationFn: () => refreshResolvedPaths(),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: queryKeys.models.all })
    },
  })
}

/** Delete a downloaded resource. */
export function useDeleteModel() {
  const qc = useQueryClient()

  return useMutation({
    mutationFn: (resourceId: string) => deleteModel(resourceId),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: queryKeys.models.all })
    },
  })
}

export interface TestModelVariables {
  resourceId: string
  subpath?: string
}

/** Load a model into memory and run a minimal inference smoke test. */
export function useTestModel() {
  return useMutation<ModelTestResult, Error, TestModelVariables>({
    mutationFn: ({ resourceId, subpath }) => testModel(resourceId, subpath),
  })
}

export interface DownloadModelVariables {
  resourceId: string
  onProgress?: (event: DownloadProgress) => void
  /**
   * Receives the http layer's cancel handle synchronously so the UI can abort
   * an in-flight download.
   */
  onCancelReady?: (cancel: () => void) => void
}

/** Resolve once *start* reports a terminal download event or is cancelled. */
function downloadWithProgress(
  start: (report: (event: DownloadProgress) => void) => () => void,
  onProgress?: (event: DownloadProgress) => void,
  onCancelReady?: (cancel: () => void) => void,
): Promise<void> {
  // `Promise.withResolvers` needs ES2024; the project targets ES2020.
  return new Promise<void>((resolve) => {
    const cancel = start((event) => {
      onProgress?.(event)
      if (event.status === 'completed' || event.status === 'failed') resolve()
    })
    onCancelReady?.(() => {
      cancel()
      resolve()
    })
  })
}

/**
 * Download a single-file resource.
 *
 * `downloadModel` is callback-based and returns a cancel handle, so the
 * mutation wraps it in a promise that resolves once the progress callback
 * reports `completed` / `failed` (or when the caller cancels).
 */
export function useDownloadModel() {
  const qc = useQueryClient()

  return useMutation({
    mutationFn: ({ resourceId, onProgress, onCancelReady }: DownloadModelVariables) =>
      downloadWithProgress(
        (report) => downloadModel(resourceId, report),
        onProgress,
        onCancelReady,
      ),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: queryKeys.models.all })
    },
  })
}

export interface DownloadSubfileVariables {
  resourceId: string
  subpath: string
  onProgress?: (event: DownloadProgress) => void
  onCancelReady?: (cancel: () => void) => void
}

/** Download a single sub-file of a multi-file resource. */
export function useDownloadModelSubfile() {
  const qc = useQueryClient()

  return useMutation({
    mutationFn: ({ resourceId, subpath, onProgress, onCancelReady }: DownloadSubfileVariables) =>
      downloadWithProgress(
        (report) => downloadModelSubfile(resourceId, subpath, report),
        onProgress,
        onCancelReady,
      ),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: queryKeys.models.all })
    },
  })
}
