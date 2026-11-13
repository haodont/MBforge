/**
 * Model discovery for OpenAI- and Anthropic-compatible `/models` endpoints.
 * Everything here is best effort: a list entry stays usable when a gateway
 * omits limits or its per-model detail endpoint is absent.
 */

import { normalizeBaseUrl, type CustomApi } from './endpointConfig.js'
import { parseJsonRecord } from './localStore.js'
import { errorMessage } from './text.js'

export interface DiscoveredModel {
  id: string
  contextWindow?: number
  maxTokens?: number
  reasoning?: boolean
}

const MODEL_DISCOVERY_TIMEOUT_MS = 5_000

function modelListCandidates(baseUrl: string, api: CustomApi): string[] {
  const base = baseUrl.replace(/\/+$/, '')
  if (/\/v1$/i.test(base)) return [`${base}/models`]
  if (api === 'anthropic-messages') return [`${base}/v1/models`]
  return [`${base}/models`, `${base}/v1/models`]
}

function discoveryHeaders(
  api: CustomApi,
  apiKey: string | undefined,
): Record<string, string> {
  const headers: Record<string, string> = { Accept: 'application/json' }
  if (!apiKey) return headers
  if (api === 'anthropic-messages') {
    headers['x-api-key'] = apiKey
    headers['anthropic-version'] = '2023-06-01'
  } else {
    headers.Authorization = `Bearer ${apiKey}`
  }
  return headers
}

function modelEntries(payload: unknown): unknown[] {
  if (Array.isArray(payload)) return payload
  const document = parseJsonRecord(payload, 'model list response')
  if (Array.isArray(document.data)) return document.data
  if (Array.isArray(document.models)) return document.models
  return []
}

function firstPositiveNumber(
  record: Record<string, unknown>,
  keys: string[],
): number | undefined {
  for (const key of keys) {
    const value = record[key]
    if (typeof value === 'number' && Number.isSafeInteger(value) && value > 0) {
      return value
    }
    if (typeof value === 'string' && /^\d+$/.test(value.trim())) {
      const parsed = Number(value)
      if (Number.isSafeInteger(parsed) && parsed > 0) return parsed
    }
  }
  return undefined
}

/**
 * Read a thinking/reasoning capability from the nonstandard fields that model
 * gateways publish. The OpenAI `/models` schema has no such field, so this
 * only answers when a gateway volunteers it.
 */
function recordReasoning(record: Record<string, unknown>): boolean | undefined {
  for (const key of [
    'reasoning',
    'supports_reasoning',
    'supportsReasoning',
    'supports_reasoning_effort',
    'supports_thinking',
    'supportsThinking',
    'thinking',
  ]) {
    const value = record[key]
    if (typeof value === 'boolean') return value
  }
  const capabilities = record.capabilities
  if (Array.isArray(capabilities)) {
    // Ollama-style capability list.
    if (capabilities.includes('thinking')) return true
  } else if (capabilities && typeof capabilities === 'object') {
    const nested = capabilities as Record<string, unknown>
    for (const key of [
      'reasoning',
      'thinking',
      'supports_reasoning',
      'supports_thinking',
    ]) {
      const value = nested[key]
      if (typeof value === 'boolean') return value
    }
  }
  // OpenRouter lists accepted request parameters per model.
  const supported = record.supported_parameters
  if (
    Array.isArray(supported) &&
    supported.some(
      (item) =>
        item === 'reasoning' ||
        item === 'reasoning_effort' ||
        item === 'include_reasoning' ||
        item === 'thinking',
    )
  ) {
    return true
  }
  return undefined
}

function applyModelMetadata(
  record: Record<string, unknown>,
  model: DiscoveredModel,
): void {
  const contextWindow = firstPositiveNumber(record, [
    'context_window',
    'contextWindow',
    'context_length',
    'max_context_length',
    'max_model_len',
    'max_input_tokens',
  ])
  const maxTokens = firstPositiveNumber(record, [
    'max_output_tokens',
    'maxOutputTokens',
    'max_completion_tokens',
    'max_tokens',
  ])
  if (model.contextWindow === undefined && contextWindow) {
    model.contextWindow = contextWindow
  }
  if (model.maxTokens === undefined && maxTokens) {
    model.maxTokens = maxTokens
  }
  if (model.reasoning === undefined) {
    const reasoning = recordReasoning(record)
    if (reasoning !== undefined) model.reasoning = reasoning
  }
}

function toDiscoveredModel(entry: unknown): DiscoveredModel | undefined {
  let record: Record<string, unknown>
  try {
    record = parseJsonRecord(entry, 'model entry')
  } catch {
    return undefined
  }
  const rawId = typeof record.id === 'string' ? record.id : record.model
  if (typeof rawId !== 'string' || !rawId.trim()) return undefined
  const model: DiscoveredModel = { id: rawId.trim() }
  applyModelMetadata(record, model)
  return model
}

/** Unwrap a detail response; OpenAI returns the object directly, some gateways wrap it in `data`. */
function modelDetailRecord(
  payload: unknown,
): Record<string, unknown> | undefined {
  let document: Record<string, unknown>
  try {
    document = parseJsonRecord(payload, 'model detail response')
  } catch {
    return undefined
  }
  if (typeof document.data !== 'object' || document.data === null) {
    return document
  }
  try {
    return parseJsonRecord(document.data, 'model detail data')
  } catch {
    return undefined
  }
}

async function enrichModelFromDetail(
  listUrl: string,
  model: DiscoveredModel,
  api: CustomApi,
  apiKey: string | undefined,
): Promise<DiscoveredModel> {
  if (
    model.contextWindow !== undefined &&
    model.maxTokens !== undefined &&
    model.reasoning !== undefined
  ) {
    return model
  }
  try {
    const detailUrl = `${listUrl.replace(/\/+$/, '')}/${encodeURIComponent(model.id)}`
    const response = await fetch(detailUrl, {
      headers: discoveryHeaders(api, apiKey),
      signal: AbortSignal.timeout(MODEL_DISCOVERY_TIMEOUT_MS),
    })
    if (!response.ok) return model
    const record = modelDetailRecord(await response.json())
    if (!record) return model
    const enriched = { ...model }
    applyModelMetadata(record, enriched)
    return enriched
  } catch {
    // A list entry remains usable when its detail endpoint is absent or slow.
    return model
  }
}

/**
 * Read models from an OpenAI- or Anthropic-compatible `/models` endpoint.
 *
 * OpenAI-compatible base URLs usually already include `/v1`; a URL without it
 * is retried with `/v1/models` before giving up. When a list entry omits its
 * context window or output limit, the per-model `/models/{model}` detail is
 * read and merged; a failed detail keeps the list entry usable.
 */
export async function discoverModels(
  baseUrl: string,
  api: CustomApi,
  apiKey?: string,
): Promise<DiscoveredModel[]> {
  const candidates = modelListCandidates(normalizeBaseUrl(baseUrl), api)
  let lastError: unknown
  for (const url of candidates) {
    try {
      const response = await fetch(url, {
        headers: discoveryHeaders(api, apiKey),
        signal: AbortSignal.timeout(MODEL_DISCOVERY_TIMEOUT_MS),
      })
      if (!response.ok) {
        lastError = new Error(`HTTP ${response.status} from ${url}`)
        if (response.status === 404 || response.status === 405) continue
        break
      }
      const models = modelEntries(await response.json())
        .map(toDiscoveredModel)
        .filter((model): model is DiscoveredModel => model !== undefined)
      const unique = [
        ...new Map(models.map((model) => [model.id, model])).values(),
      ]
      if (unique.length > 0) {
        return await Promise.all(
          unique.map((model) => enrichModelFromDetail(url, model, api, apiKey)),
        )
      }
      lastError = new Error(`No models returned by ${url}`)
    } catch (error) {
      lastError = error
      break
    }
  }
  throw new Error(errorMessage(lastError) || 'Model discovery failed')
}
