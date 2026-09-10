/** Readiness diagnostics — subsystem health summary, LLM probe, demo run. */

import { httpGet, httpPost, invokeWithError } from './_utils'
import { ErrorCode } from '@/utils/errors'

export interface ReadinessLibrary {
  configured: boolean
  path: string | null
  exists: boolean
  writable: boolean
  error: string | null
}

export interface ReadinessDatabase {
  ok: boolean
  error: string | null
}

export type ReadinessModelStatus = 'ready' | 'partial' | 'missing' | 'error' | (string & {})

export interface ReadinessModel {
  id: string
  name: string
  status: ReadinessModelStatus
  local_path: string | null
  size_mb: number | null
  expected_size_mb: number | null
  cache_dir: string | null
  last_error: string | null
}

export interface ReadinessLlm {
  configured: boolean
  provider: string | null
  model: string | null
  base_url: string | null
  has_api_key: boolean
}

export interface ReadinessOcr {
  chain: string[]
  error: string | null
}

export interface ReadinessSummary {
  library: ReadinessLibrary
  database: ReadinessDatabase
  models: ReadinessModel[]
  llm: ReadinessLlm
  ocr: ReadinessOcr
}

export interface ProbeLlmResult {
  ok: boolean
  latency_ms: number | null
  error: string | null
  provider: string
  model: string
}

export interface DemoRunResult {
  ok: boolean
  task_id: string | null
  file_path: string
  error: string | null
}

/** Aggregate readiness summary across library, DB, models, LLM and OCR. */
export async function readinessSummary(): Promise<ReadinessSummary> {
  return invokeWithError(
    () => httpGet<ReadinessSummary>('/api/v1/diagnostics/summary'),
    ErrorCode.ApiError,
  )
}

/** Probe the configured LLM endpoint and measure latency. */
export async function readinessProbeLlm(): Promise<ProbeLlmResult> {
  return invokeWithError(
    () => httpPost<ProbeLlmResult>('/api/v1/diagnostics/probe-llm'),
    ErrorCode.ApiError,
  )
}

/** Enqueue a small demo document through the pipeline as a smoke test. */
export async function readinessDemoRun(): Promise<DemoRunResult> {
  return invokeWithError(
    () => httpPost<DemoRunResult>('/api/v1/diagnostics/demo-run'),
    ErrorCode.ApiError,
  )
}
