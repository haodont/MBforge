/** 模型下载 — HTTP API (FastAPI backend) */

import { httpPost, httpFetch, invokeWithError } from './_utils'
import { ErrorCode } from '@/utils/errors'
import { resourcesCatalog } from './environment'

export interface SubfileStatus {
  label: string          // 友好标签，如 "doc" / "general"
  relpath: string        // 相对仓库根路径
  local_path: string     // 完整本地路径
  ready: boolean
  size_mb: number
}

export interface DownloadModel {
  id: string
  name: string
  type: string
  description: string
  ms_repo: string
  downloaded: boolean
  downloading: boolean
  local_path: string
  /** 期望路径（模型应该被检测到的位置）。download 按钮用它提示用户。 */
  expected_path: string
  license: string
  license_url: string
  size_mb: number
  source_url: string
  /** 多文件资源（如 MolDetv2）的逐文件状态。空数组 = 单文件资源。 */
  subfiles: SubfileStatus[]
}

export interface DownloadedModel {
  id: string
  name: string
  path: string
  size_mb: number
  type: string
  in_catalog: boolean
}

export interface DownloadProgress {
  resource_id: string  // 模型/资源 ID，区分同时下载的多个模型
  status: string       // "connecting" | "downloading" | "completed" | "failed"
  file: string
  file_progress: number
  file_index: number
  total_files: number
  error: string
}

function str(val: unknown, fallback = ''): string {
  return typeof val === 'string' ? val : fallback
}

/** 根据资源 ID 推断前端展示用的模型类别（与 ModelsTab typeLabels 对齐）。 */
function inferModelType(id: string): string {
  if (id === 'embedding') return 'embedding'
  if (id === 'reranker') return 'reranker'
  if (id === 'moldet' || id === 'molparser') return 'detection'
  return 'model'
}

/**
 * 列出所有可用模型（catalog + 实时状态）。
 * 内部组合 `resources_catalog` 与 `resources_status`。
 */
export async function listModels(): Promise<{ success: boolean; models: DownloadModel[]; error?: string }> {
  try {
    // The backend wraps the list in {"resources": [...]}.
    const data = await httpPost<{ resources?: Record<string, unknown>[] }>('/api/v1/resources/catalog')
    const catalog = data.resources ?? []
    const models: DownloadModel[] = []
    for (const item of catalog) {
      const id = str(item.id)
      if (!id) continue
      if (str(item.type) !== 'model') continue
      const status = await invokeWithError(
        () => httpPost<{
          status: string
          local_path: string
          size_mb: number
          expected_path: string
          subfiles: { label: string; relpath: string; local_path: string; ready: boolean; size_mb: number }[]
        }>('/api/v1/resources/status', { resource_id: id }),
        ErrorCode.ApiError,
      )
      models.push({
        id,
        name: str(item.name, id),
        type: inferModelType(id),
        description: str(item.description),
        ms_repo: str(item.ms_repo),
        downloaded: status.status === 'ready',
        downloading: false,
        local_path: status.local_path,
        expected_path: status.expected_path,
        license: str(item.license),
        license_url: str(item.license_url),
        size_mb: Number(item.size_mb ?? 0),
        source_url: str(item.source_url),
        subfiles: status.subfiles,
      })
    }
    return { success: true, models }
  } catch (e) {
    return { success: false, models: [], error: String(e) }
  }
}

/**
 * 列出已下载模型。
 * 基于 catalog 过滤出状态为 ready 的条目。
 */
export async function listDownloaded(): Promise<{ success: boolean; models: DownloadedModel[]; model_dir: string; error?: string }> {
  try {
    const catalog = await resourcesCatalog()
    const models: DownloadedModel[] = []
    for (const item of catalog) {
      const id = str(item.id)
      if (!id) continue
      const status = await invokeWithError(
        () => httpPost<{ status: string; local_path: string; size_mb: number }>('/api/v1/resources/status', { resource_id: id }),
        ErrorCode.ApiError,
      )
      if (status.status === 'ready') {
        models.push({
          id,
          name: str(item.name, id),
          path: status.local_path,
          size_mb: status.size_mb,
          type: inferModelType(id),
          in_catalog: true,
        })
      }
    }
    const dirInfo = await httpPost<{ mbforge: { path: string } }>('/api/v1/resource/cache-dir-info')
    return { success: true, models, model_dir: dirInfo.mbforge.path }
  } catch (e) {
    return { success: false, models: [], model_dir: '', error: String(e) }
  }
}

/**
 * 下载模型（通过 HTTP API 触发，返回进度回调）
 *
 * @param resourceId - 资源 ID（如 "embedding", "molparser"）
 * @param onProgress - 进度回调
 * @returns 取消函数
 */
export function downloadModel(
  resourceId: string,
  onProgress: (event: DownloadProgress) => void,
): () => void {
  const controller = new AbortController()
  let aborted = false

  const start = async () => {
    try {
      const resp = await invokeWithError(
        () => httpFetch<{ success?: boolean; path?: string; status?: string }>('/api/v1/resource/download', {
          method: 'POST',
          body: JSON.stringify({ resource_id: resourceId }),
          signal: controller.signal,
        }),
        ErrorCode.ApiError,
      )
      const path = resp.path ?? ''
      if (!aborted && !controller.signal.aborted) {
        onProgress({
          resource_id: resourceId,
          status: 'completed',
          file: path,
          file_progress: 1,
          file_index: 0,
          total_files: 1,
          error: '',
        })
      }
    } catch (err) {
      if (aborted || controller.signal.aborted) return
      console.error(`[downloadModel ${resourceId}] failed:`, err)
      onProgress({
        resource_id: resourceId,
        status: 'failed',
        file: '',
        file_progress: 0,
        file_index: 0,
        total_files: 0,
        error: String(err),
      })
    }
  }
  void start()

  return () => {
    aborted = true
    controller.abort()
  }
}

/** 删除已下载的模型 */
export async function deleteModel(resourceId: string): Promise<void> {
  await invokeWithError(
    () => httpPost<unknown>('/api/v1/resource/delete', { resource_id: resourceId }),
    ErrorCode.ApiError,
  )
}

/** 下载多文件资源中的单个子文件 */
export function downloadModelSubfile(
  resourceId: string,
  subpath: string,
  onProgress: (event: DownloadProgress) => void,
): () => void {
  const controller = new AbortController()
  let aborted = false

  const start = async () => {
    try {
      await invokeWithError(
        () => httpFetch<string>('/api/v1/resource/download-subfile', {
          method: 'POST',
          body: JSON.stringify({ resource_id: resourceId, subpath }),
          signal: controller.signal,
        }),
        ErrorCode.ApiError,
      )
      if (!aborted && !controller.signal.aborted) {
        onProgress({
          resource_id: resourceId,
          status: 'completed',
          file: subpath,
          file_progress: 1,
          file_index: 0,
          total_files: 1,
          error: '',
        })
      }
    } catch (err) {
      if (aborted || controller.signal.aborted) return
      onProgress({
        resource_id: resourceId,
        status: 'failed',
        file: subpath,
        file_progress: 0,
        file_index: 0,
        total_files: 0,
        error: String(err),
      })
    }
  }
  void start()

  return () => {
    aborted = true
    controller.abort()
  }
}

/** 删除多文件资源中的单个子文件 */
export async function deleteModelSubfile(resourceId: string, subpath: string): Promise<void> {
  await invokeWithError(
    () => httpPost<unknown>('/api/v1/resource/delete-subfile', { resource_id: resourceId, subpath }),
    ErrorCode.ApiError,
  )
}

/** 测试模型：实际加载到内存 + 最小推理。返回 {ok, error, duration_ms} */
export interface ModelTestResult {
  ok: boolean
  error: string
  duration_ms: number
}

export async function testModel(
  resourceId: string,
  subpath?: string,
): Promise<ModelTestResult> {
  return invokeWithError(
    () => httpPost<ModelTestResult>('/api/v1/resource/test', { resource_id: resourceId, subpath }),
    ErrorCode.ApiError,
  )
}