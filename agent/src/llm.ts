/** LLM provider I/O for the MBForge agent sidecar.
 *
 * The sidecar is the only component that talks to an LLM provider. The Python
 * backend merely persists the settings and the browser only relays form values,
 * so provider defaults, the model-list probe and the connectivity probe live
 * here instead of in a second Python implementation.
 */

import { existsSync } from 'node:fs'
import { readFile } from 'node:fs/promises'
import { homedir } from 'node:os'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

export interface AgentLlmConfig {
  provider: string
  model: string
  apiKey: string
  baseUrl: string
  maxTokens: number
  requestTimeoutMs: number
}

export interface ProviderModelOption {
  value: string
  label: string
}

export interface LlmProbeResult {
  ok: boolean
  latency_ms: number | null
  error: string | null
  provider: string
  model: string
}

export type ProviderKind = 'openai_compatible' | 'anthropic' | 'ollama'

const OPENAI_COMPATIBLE = ['openai_compatible', 'openai', 'deepseek']

/** Chat-endpoint defaults for the providers the Settings UI offers.
 *  Anthropic is listed even though it needs no override: unlike the Python
 *  SDK it replaced, the model registry requires an explicit base URL. */
const DEFAULT_BASE_URLS: Record<string, string> = {
  openai_compatible: 'https://api.openai.com/v1',
  openai: 'https://api.openai.com/v1',
  deepseek: 'https://api.deepseek.com/v1',
  anthropic: 'https://api.anthropic.com',
  ollama: 'http://127.0.0.1:11434/v1',
}

const DEFAULT_OLLAMA_BASE = 'http://127.0.0.1:11434'

export function asRecord(value: unknown): Record<string, unknown> {
  return typeof value === 'object' && value !== null ? value as Record<string, unknown> : {}
}

export function stringValue(value: unknown, fallback: string, maxLength = 512): string {
  if (typeof value !== 'string') return fallback
  const trimmed = value.trim()
  return trimmed.length > 0 && trimmed.length <= maxLength ? trimmed : fallback
}

function numberValue(value: unknown, fallback: number, min: number, max: number): number {
  return typeof value === 'number' && Number.isFinite(value)
    ? Math.min(max, Math.max(min, value))
    : fallback
}

/** Describe a fetch failure; Node hides the real reason in error.cause. */
export function describeFetchError(error: unknown): string {
  if (!(error instanceof Error)) return String(error)
  if (error.name === 'TimeoutError') return 'timeout'
  const cause = (error as { cause?: unknown }).cause
  const detail = cause && typeof cause === 'object'
    ? (cause as { code?: unknown; message?: unknown }).code ?? (cause as { message?: unknown }).message
    : undefined
  return typeof detail === 'string' && detail ? error.message + ' (' + detail + ')' : error.message
}

/** Render an error without echoing the configured API key back to the browser. */
export function sanitizeError(error: unknown, apiKey: unknown): string {
  const message = error instanceof Error ? error.message : String(error)
  const secret = typeof apiKey === 'string' ? apiKey : ''
  const cleaned = secret ? message.split(secret).join('***') : message
  return cleaned.slice(0, 300)
}

/** Resolve settings.json the same way mbforge.foundation.paths does: a source
 *  checkout keeps its runtime data in <source root>/library, an installed build
 *  falls back to ~/MBForge. Without this the sidecar read a path that does not
 *  exist and silently lost every persisted setting. */
export function settingsPath(): string {
  const override = process.env.MBFORGE_SETTINGS_PATH
  if (override) return override
  const sourceRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..', '..')
  if (existsSync(join(sourceRoot, 'pyproject.toml'))) {
    return join(sourceRoot, 'library', 'settings.json')
  }
  return join(homedir(), 'MBForge', 'settings.json')
}

export async function loadPersistedLlmConfig(): Promise<Record<string, unknown>> {
  try {
    const parsed = JSON.parse(await readFile(settingsPath(), 'utf8')) as unknown
    return asRecord(asRecord(parsed).llm)
  } catch {
    return {}
  }
}

/** Classify a provider; unknown names fail fast instead of silently posting to
 *  the OpenAI default endpoint. Mirrors the Python provider_kind it replaced. */
export function providerKind(provider: string): ProviderKind {
  const key = (provider || '').trim().toLowerCase()
  if (OPENAI_COMPATIBLE.includes(key)) return 'openai_compatible'
  if (key === 'anthropic') return 'anthropic'
  if (key === 'ollama') return 'ollama'
  throw new Error('unsupported LLM provider: ' + provider)
}

export function defaultBaseUrl(provider: string): string {
  return DEFAULT_BASE_URLS[(provider || '').trim().toLowerCase()] ?? ''
}

/** Overlay explicit values on the persisted ones, ignoring blanks and the
 *  redacted placeholder GET /settings returns for a stored secret. */
export function mergeConfig(raw: unknown, persisted: Record<string, unknown>): Record<string, unknown> {
  const value = asRecord(raw)
  const merged = { ...persisted }
  for (const [key, candidate] of Object.entries(value)) {
    if (candidate !== '' && candidate !== '***') merged[key] = candidate
  }
  return merged
}

export interface ProviderTarget {
  provider: string
  baseUrl: string
  apiKey: string
}

/** Resolve the provider, base URL and key for a discovery call.
 *
 * Deliberately does not require an API key the way readConfig does: listing
 * models is read-only, and a keyless local gateway still has a real catalog.
 */
export function resolveProviderTarget(
  raw: unknown,
  persisted: Record<string, unknown>,
): ProviderTarget {
  const value = mergeConfig(raw, persisted)
  const provider = stringValue(
    value.provider ?? process.env.MBFORGE_AGENT_PROVIDER,
    'openai_compatible',
    80,
  ).toLowerCase()
  providerKind(provider)
  const apiKey = stringValue(
    value.api_key ?? value.apiKey ?? process.env.MBFORGE_AGENT_API_KEY,
    provider === 'ollama' ? 'ollama' : '',
    4096,
  )
  const baseUrl = stringValue(
    value.base_url ?? value.baseUrl ?? process.env.MBFORGE_AGENT_BASE_URL,
    defaultBaseUrl(provider),
    2048,
  ).replace(/\/$/, '')
  return { provider, baseUrl, apiKey }
}

export function readConfig(raw: unknown, persisted: Record<string, unknown>): AgentLlmConfig {
  const value = mergeConfig(raw, persisted)
  const provider = stringValue(
    value.provider ?? process.env.MBFORGE_AGENT_PROVIDER,
    'openai_compatible',
    80,
  ).toLowerCase()
  providerKind(provider)
  const apiKey = stringValue(
    value.api_key ?? value.apiKey ?? process.env.MBFORGE_AGENT_API_KEY,
    provider === 'ollama' ? 'ollama' : '',
    4096,
  )
  const model = stringValue(value.model ?? process.env.MBFORGE_AGENT_MODEL, 'gpt-4o-mini', 256)
  const baseUrl = stringValue(
    value.base_url ?? value.baseUrl ?? process.env.MBFORGE_AGENT_BASE_URL,
    defaultBaseUrl(provider),
    2048,
  ).replace(/\/$/, '')
  const requestTimeoutSeconds = numberValue(
    value.request_timeout ?? process.env.MBFORGE_AGENT_REQUEST_TIMEOUT,
    60,
    1,
    600,
  )

  if (provider !== 'ollama' && !apiKey) {
    throw new Error('An API key is required for the configured LLM provider')
  }

  return {
    provider,
    model,
    apiKey,
    baseUrl,
    maxTokens: Math.round(numberValue(value.max_tokens ?? value.maxTokens, 4096, 256, 32768)),
    requestTimeoutMs: Math.round(requestTimeoutSeconds * 1000),
  }
}

function trimSlashes(url: string): string {
  return url.replace(/\/+$/, '')
}

function joinUrl(baseUrl: string, path: string): string {
  return trimSlashes(baseUrl) + path
}

/** Ollama serves its native API on the raw port, not under the /v1 the chat
 *  endpoint uses, so the OpenAI-compatible suffix has to come off. */
function ollamaNativeBase(baseUrl: string): string {
  const base = trimSlashes(baseUrl) || DEFAULT_OLLAMA_BASE
  return base.endsWith('/v1') ? base.slice(0, -3) : base
}

/** Query the provider model-list API (OpenAI /models, Anthropic /v1/models,
 *  Ollama /api/tags) so the Settings dropdown shows real models. */
export async function fetchProviderModels(
  provider: string,
  baseUrl: string,
  apiKey: string,
  timeoutMs = 10000,
): Promise<ProviderModelOption[]> {
  const kind = providerKind(provider)
  const headers: Record<string, string> = {}
  let url: string
  let key: string
  let labelKey: string | null = null

  if (kind === 'openai_compatible') {
    url = joinUrl(baseUrl.trim() || DEFAULT_BASE_URLS.openai_compatible, '/models')
    if (apiKey) headers.Authorization = 'Bearer ' + apiKey
    key = 'id'
  } else if (kind === 'anthropic') {
    const base = baseUrl.trim() || DEFAULT_BASE_URLS.anthropic
    url = trimSlashes(base).endsWith('/v1')
      ? joinUrl(base, '/models')
      : joinUrl(base, '/v1/models')
    if (apiKey) headers['x-api-key'] = apiKey
    headers['anthropic-version'] = '2023-06-01'
    key = 'id'
    labelKey = 'display_name'
  } else {
    url = joinUrl(ollamaNativeBase(baseUrl), '/api/tags')
    key = 'name'
  }

  let response: Response
  try {
    response = await fetch(url, { headers, signal: AbortSignal.timeout(timeoutMs) })
  } catch (error) {
    throw new Error('cannot reach model service ' + url + ': ' + describeFetchError(error))
  }

  if (response.status === 401 || response.status === 403) {
    throw new Error('authentication failed (HTTP ' + response.status + ') - check the API key')
  }
  if (response.status !== 200) {
    throw new Error('model service returned HTTP ' + response.status + ' - check the base URL')
  }

  let payload: unknown
  try {
    payload = await response.json()
  } catch {
    throw new Error('model service returned an invalid response')
  }

  const entries = asRecord(payload)[kind === 'ollama' ? 'models' : 'data']
  if (!Array.isArray(entries)) throw new Error('model service returned no model list')

  const rows: ProviderModelOption[] = []
  for (const entry of entries) {
    const record = asRecord(entry)
    const value = record[key]
    if (typeof value !== 'string') continue
    const label = labelKey ? record[labelKey] : undefined
    rows.push({ value, label: typeof label === 'string' && label ? label : value })
  }

  const seen = new Set<string>()
  const unique: ProviderModelOption[] = []
  for (const row of rows) {
    if (seen.has(row.value)) continue
    seen.add(row.value)
    unique.push(row)
  }
  unique.sort((a, b) => a.value.toLowerCase().localeCompare(b.value.toLowerCase()))
  return unique
}

/** Send a one-token chat request so the UI can prove the configured endpoint,
 *  credentials and model all work. Never throws: failures come back as data. */
export async function probeLlm(config: AgentLlmConfig): Promise<LlmProbeResult> {
  const started = Date.now()
  const failure = (error: string): LlmProbeResult => ({
    ok: false,
    latency_ms: null,
    error,
    provider: config.provider,
    model: config.model,
  })

  const ping = [{ role: 'user', content: 'ping' }]
  let url: string
  let headers: Record<string, string>
  let body: Record<string, unknown>

  if (config.provider === 'anthropic') {
    url = joinUrl(config.baseUrl || DEFAULT_BASE_URLS.anthropic, '/v1/messages')
    headers = {
      'content-type': 'application/json',
      'x-api-key': config.apiKey,
      'anthropic-version': '2023-06-01',
    }
    body = { model: config.model, max_tokens: 1, messages: ping }
  } else if (config.provider === 'ollama') {
    url = joinUrl(ollamaNativeBase(config.baseUrl), '/api/chat')
    headers = { 'content-type': 'application/json' }
    body = { model: config.model, messages: ping, stream: false }
  } else {
    url = joinUrl(config.baseUrl || DEFAULT_BASE_URLS.openai_compatible, '/chat/completions')
    headers = {
      'content-type': 'application/json',
      authorization: 'Bearer ' + config.apiKey,
    }
    body = { model: config.model, max_tokens: 1, messages: ping }
  }

  try {
    const response = await fetch(url, {
      method: 'POST',
      headers,
      body: JSON.stringify(body),
      signal: AbortSignal.timeout(config.requestTimeoutMs),
    })
    if (!response.ok) {
      const detail = sanitizeError(await response.text(), config.apiKey).slice(0, 200)
      return failure('HTTP ' + response.status + ': ' + detail)
    }
  } catch (error) {
    return failure(describeFetchError(error))
  }

  return {
    ok: true,
    latency_ms: Date.now() - started,
    error: null,
    provider: config.provider,
    model: config.model,
  }
}
