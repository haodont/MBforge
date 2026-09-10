/** Resource manager — environment check, model paths, catalog via HTTP. */

import { httpPost, httpGet, invokeWithError } from './_utils'
import { ErrorCode } from '@/utils/errors'

export interface ResourceStatusItem {
  id: string
  name: string
  type: string
  status: string
  local_path: string
  size_mb: number
  version: string
  error: string
}

export interface EnvironmentReport {
  python_version: string
  gpu_available: boolean
  gpu_name: string
  cuda_version: string
  summary: string
  resources: ResourceStatusItem[]
}

/** 全量环境检查 */
export async function resourcesCheck(): Promise<EnvironmentReport> {
  return invokeWithError(
    () => httpGet<EnvironmentReport>('/api/v1/environment/check'),
    ErrorCode.ApiError,
  )
}

/** 检查单个资源状态 */
export async function resourcesStatus(resourceId: string): Promise<ResourceStatusItem> {
  return invokeWithError(
    () => httpPost<ResourceStatusItem>('/api/v1/resources/status', { resource_id: resourceId }),
    ErrorCode.ApiError,
  )
}

/** 获取已下载模型的本地路径 */
export async function resourcesGetModelPath(resourceId: string): Promise<string | null> {
  return invokeWithError(
    () => httpPost<string | null>('/api/v1/resources/model-path', { resource_id: resourceId }),
    ErrorCode.ApiError,
  )
}

/** 获取资源目录（纯元数据） */
export async function resourcesCatalog(): Promise<Record<string, unknown>[]> {
  const resp = await httpPost<{ resources: Record<string, unknown>[] }>('/api/v1/resources/catalog')
  return resp.resources
}

/** 获取模型缓存目录信息 */
export async function modelsCacheDirInfo(): Promise<{
  mbforge: { path: string; exists: boolean; size_mb: number }
  huggingface: { path: string; exists: boolean; size_mb: number; env_var: string }
  modelscope: { path: string; exists: boolean; size_mb: number; env_var: string }
}> {
  return httpPost('/api/v1/resource/cache-dir-info')
}

/** 刷新模型路径解析（重新扫描缓存目录并写入 resolved_paths.json） */
export async function refreshResolvedPaths(): Promise<{
  success: boolean
  resources: Record<string, string>
}> {
  return invokeWithError(
    () => httpPost<{ success: boolean; resources: Record<string, string> }>('/api/v1/resources/refresh-paths'),
    ErrorCode.ApiError,
  )
}
