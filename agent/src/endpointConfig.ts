/**
 * Custom-endpoint configuration contract: protocol options, the shape of a
 * saved endpoint, and the validation rules shared by the `/endpoint` command
 * and the models.json/auth.json store. Pure functions; no file or network IO.
 */

export const CUSTOM_PROVIDER_ID = 'custom'
export const DEFAULT_CONTEXT_WINDOW = 128_000
export const DEFAULT_MAX_TOKENS = 8_192

export type CustomApi =
  'openai-completions' | 'openai-responses' | 'anthropic-messages'

export const CUSTOM_API_OPTIONS: ReadonlyArray<{
  value: CustomApi
  label: string
}> = [
  {
    value: 'openai-completions',
    label: 'OpenAI-compatible · chat completions',
  },
  { value: 'openai-responses', label: 'OpenAI-compatible · responses' },
  { value: 'anthropic-messages', label: 'Anthropic-compatible · messages' },
]

export interface ExistingEndpoint {
  baseUrl?: string
  api?: CustomApi
  modelId?: string
  modelName?: string
  contextWindow?: number
  maxTokens?: number
  reasoning?: boolean
  hasKey: boolean
}

export interface CustomEndpointInput {
  baseUrl: string
  api: CustomApi
  modelId: string
  modelName?: string
  contextWindow?: number
  maxTokens?: number
  /** Whether the model accepts thinking/reasoning parameters. */
  reasoning?: boolean
  /** Omit to keep the existing saved key. */
  apiKey?: string
}

export interface SavedEndpoint {
  modelsPath: string
  authPath: string
  providerId: string
}

/** Read a stored protocol value, or `undefined` when it is not supported. */
export function readApi(value: unknown): CustomApi | undefined {
  return CUSTOM_API_OPTIONS.find((option) => option.value === value)?.value
}

export function normalizeApi(value: string): CustomApi {
  const api = readApi(value)
  if (!api) throw new Error(`Unsupported custom API protocol: ${value}`)
  return api
}

export function normalizeBaseUrl(raw: string): string {
  const value = raw.trim()
  if (!value) throw new Error('API base URL is required')
  let parsed: URL
  try {
    parsed = new URL(value)
  } catch {
    throw new Error('API base URL is not a valid URL')
  }
  if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') {
    throw new Error('API base URL must start with http:// or https://')
  }
  if (parsed.username || parsed.password) {
    throw new Error('API base URL must not contain credentials')
  }
  return value.replace(/\/+$/, '')
}

function trimmed(raw: string, label: string, maxLength: number): string {
  const value = raw.trim()
  if (!value) throw new Error(`${label} is required`)
  if (value.length > maxLength) throw new Error(`${label} is too long`)
  if (/[\u0000-\u001f\u007f]/.test(value)) {
    throw new Error(`${label} contains control characters`)
  }
  return value
}

export function normalizeModelId(raw: string): string {
  return trimmed(raw, 'Model ID', 256)
}

export function normalizeApiKey(raw: string): string {
  return trimmed(raw, 'API key', 8_192)
}

export function normalizeTokenCount(value: number, label: string): number {
  if (!Number.isSafeInteger(value) || value <= 0) {
    throw new Error(`${label} must be a positive integer`)
  }
  return value
}

/** Parse a token count such as 128000, 128k or 1m. */
export function parseTokenCount(raw: string, label: string): number {
  const value = raw.trim().toLowerCase().replace(/_/g, '')
  const match = /^(\d+(?:\.\d+)?)([km])?$/.exec(value)
  if (!match) {
    throw new Error(
      `${label} must be a positive integer (for example 128000 or 128k)`,
    )
  }
  const multiplier = match[2] === 'k' ? 1_000 : match[2] === 'm' ? 1_000_000 : 1
  return normalizeTokenCount(Math.round(Number(match[1]) * multiplier), label)
}

/**
 * Resolve a stored secret reference: `$ENV_VAR`, `${ENV_VAR}`, `$$` and `$!`
 * escapes. A `!command` credential is left to pi and resolves to `undefined`
 * here, as does an unset environment variable.
 */
export function resolveSecret(raw: string | undefined): string | undefined {
  if (!raw) return undefined
  const value = raw.trim()
  if (!value) return undefined
  if (value === '$$') return '$'
  if (value === '$!') return '!'
  // Command-backed credentials are intentionally not run by discovery.
  if (value.startsWith('!')) return undefined
  if (value.startsWith('${') && value.endsWith('}')) {
    const name = value.slice(2, -1)
    return name ? process.env[name] || undefined : undefined
  }
  if (value.startsWith('$')) {
    const name = value.slice(1)
    return name ? process.env[name] || undefined : undefined
  }
  return value
}
