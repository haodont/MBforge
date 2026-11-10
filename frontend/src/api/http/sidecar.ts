/** Model-service status and environment commands.
 *
 * - `sidecarStatus`: local model-service health; the legacy `/sidecar` path is
 *   kept for the Settings model-service panel.
 * - `environmentCheck`: probes Python via the model-service HTTP API.
 */

import { httpGet, invokeWithError } from './_utils'
import { ErrorCode } from '@/utils/errors'

export interface SidecarStatus {
  healthy: boolean
  restartCount: number
  state: 'online' | 'offline'
  uptimeSecs: number
  lastError: string | null
  /** Per-model loading status pushed via /health and the model_loading SSE. */
  models?: Record<string, string>
}

/** Read sidecar health + restart count + uptime. */
export async function sidecarStatus(): Promise<SidecarStatus> {
  return invokeWithError(
    () => httpGet<SidecarStatus>('/api/v1/sidecar/status'),
    ErrorCode.ApiError,
  )
}

/** 探测 Python sidecar 环境信息（Python 版本、GPU、CUDA、库依赖）。 */
export async function environmentCheck(): Promise<unknown> {
  return invokeWithError(
    () => httpGet<unknown>('/api/v1/environment/check'),
    ErrorCode.ApiError,
  )
}
