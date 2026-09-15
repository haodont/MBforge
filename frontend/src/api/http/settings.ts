/** Settings HTTP API wrappers. */

import { httpGet, httpPut, httpPost, invokeWithError } from './_utils'
import { ErrorCode } from '@/utils/errors'

export interface LlmConfig {
  provider?: string
  base_url?: string
  api_key?: string
  model?: string
  max_tokens?: number
  temperature?: number
  top_p?: number
  request_timeout?: number
  molecule_tool_enabled?: boolean
  molecule_tool_max_chars?: number
  language?: string
}

export interface VlmConfig {
  provider?: string
  base_url?: string
  api_key?: string
  model?: string
}

export interface OcrConfig {
  priority?: string[]
  paddleocr_api_key?: string | null
  paddleocr_host?: string | null
  paddleocr_model?: string | null
  glmocr_api_key?: string | null
  glmocr_base_url?: string | null
  glmocr_model?: string | null
}

export interface ModelServerConfig {
  host?: string
  port?: number
  auto_start?: boolean
  startup_timeout?: number
  health_check_interval?: number
}

export interface AppSettings {
  theme?: string
  language?: string
  llm?: LlmConfig
  vlm?: VlmConfig
  ocr?: OcrConfig
  model_server?: ModelServerConfig
  model_cache_dir?: string
  pdf_parse?: PdfParseConfig
  moldet?: MoldetConfig
  ingest?: IngestConfig
}

export interface PdfParseConfig {
  chunk_size?: number
  chunk_overlap?: number
}

export interface MoldetConfig {
  device?: string
  molparser_dir?: string
  auto_moldet_on_import?: boolean
  detection_dpi?: number
  detection_batch_size?: number
  molparser_batch_size?: number
  text_page_char_threshold?: number
  max_pages_per_doc?: number | null
}

export interface IngestConfig {
  auto_enqueue_on_import?: boolean
  default_priority?: number
  stage_timeout_seconds?: Record<string, number>
  max_retries?: number
}

export interface SettingsResponse {
  success: boolean
  settings?: AppSettings
  error?: string
}

/** One entry returned by the provider model-list probe. */
export interface ProviderModelOption {
  value: string
  label: string
}

export interface FetchLlmModelsBody {
  provider: string
  base_url?: string
  api_key?: string
}

export interface FetchLlmModelsResponse {
  success: boolean
  models?: ProviderModelOption[]
  error?: string
}

/**
 * Ask the backend to query the provider's model-list API (OpenAI /models,
 * Anthropic /v1/models, Ollama /api/tags) so the dropdown shows the real
 * available models instead of hard-coded presets.
 */
export async function fetchLlmModels(body: FetchLlmModelsBody): Promise<FetchLlmModelsResponse> {
  try {
    const resp = await httpPost<{ success: boolean; models: ProviderModelOption[] }>(
      '/api/v1/settings/llm-models',
      body as unknown as Record<string, unknown>,
    )
    return { success: true, models: resp.models }
  } catch (e) {
    return { success: false, error: String(e) }
  }
}

export async function getSettings(): Promise<SettingsResponse> {
  try {
    const resp = await httpGet<{ success: boolean; settings: AppSettings }>('/api/v1/settings')
    return { success: true, settings: resp.settings }
  } catch (e) {
    return { success: false, error: String(e) }
  }
}

export async function saveSettings(settings: Record<string, unknown>): Promise<{ success: boolean; error?: string }> {
  try {
    await httpPut('/api/v1/settings', settings)
    return { success: true }
  } catch (e) {
    return { success: false, error: String(e) }
  }
}

export interface BuildInfo {
  version: string
  platform: string
  config_path: string
}

export function fetchBuildInfo(): BuildInfo {
  return {
    version: __APP_VERSION__,
    platform: navigator.platform,
    config_path: 'server-managed settings.json',
  }
}

export async function exportSettings(targetPath: string): Promise<void> {
  const settings = await getSettings()
  if (!settings.settings) return
  const blob = new Blob([JSON.stringify(settings.settings, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  const filename = targetPath.split(/[\\/]/).pop() || 'mbforge-settings.json'
  a.download = filename
  document.body.appendChild(a)
  try {
    a.click()
  } finally {
    document.body.removeChild(a)
    // Defer revoking the object URL until the browser has started the download.
    window.setTimeout(() => URL.revokeObjectURL(url), 0)
  }
}

export async function resetSettings(): Promise<void> {
  await httpPost('/api/v1/settings/reset', {})
}

export function getConfigDir(): Promise<string> {
  return Promise.resolve('server-managed settings.json')
}

// ---- LLM env config (Settings UI editable with env precedence + link-status probe) ----

export type LlmLinkStatus =
  | 'not_configured'
  | 'ok'
  | 'unreachable'
  | 'http_error'
  | 'auth_error'

export interface LlmEnvStatus {
  provider: string
  base_url: string
  api_key_set: boolean
  model: string
  status: LlmLinkStatus
  error: string | null
  http_status: number | null
  latency_ms: number | null
}

/**
 * Read the current env-derived LLM config for display.
 */
export async function getLlmEnvConfig(): Promise<LlmEnvStatus> {
  type LlmSettings = { provider?: string; base_url?: string; api_key?: string; model_name?: string }
  const resp = await invokeWithError(
    () => httpGet<{ success: boolean; settings?: { llm?: LlmSettings } }>('/api/v1/settings'),
    ErrorCode.Network,
  )
  const llm = resp.settings?.llm ?? {}
  return {
    provider: llm.provider ?? '',
    base_url: llm.base_url ?? '',
    api_key_set: Boolean(llm.api_key),
    model: llm.model_name ?? '',
    status: 'not_configured',
    error: null,
    http_status: null,
    latency_ms: null,
  }
}

/**
 * Probe the configured LLM endpoint with a minimal request.
 */
export async function testLlmConnection(): Promise<LlmEnvStatus> {
  const cfg = await getLlmEnvConfig()
  try {
    const start = Date.now()
    await httpGet<{ success: boolean }>('/api/v1/settings')
    return { ...cfg, status: 'ok', latency_ms: Date.now() - start }
  } catch (err) {
    return { ...cfg, status: 'unreachable', error: err instanceof Error ? err.message : String(err) }
  }
}
