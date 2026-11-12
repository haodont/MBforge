import { join } from 'node:path'

import {
  getAgentDir,
  type ExtensionAPI,
  type ExtensionCommandContext,
} from '@earendil-works/pi-coding-agent'
import { Type } from 'typebox'
import { Value } from 'typebox/value'

import { atomicWriteSync, readJsonFileSync } from './localStore.js'

export const CUSTOM_PROVIDER_ID = 'custom'
const CUSTOM_PROVIDER_NAME = 'Custom endpoint'
const MODELS_SCHEMA = 'https://pi.dev/schemas/models.schema.json'
const DEFAULT_CONTEXT_WINDOW = 128_000
const DEFAULT_MAX_TOKENS = 8_192
const JSON_RECORD = Type.Record(Type.String(), Type.Unknown())

export type CustomApi =
  | 'openai-completions'
  | 'openai-responses'
  | 'anthropic-messages'

export const CUSTOM_API_OPTIONS: ReadonlyArray<{
  value: CustomApi
  label: string
}> = [
  { value: 'openai-completions', label: 'OpenAI-compatible · chat completions' },
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

export interface DiscoveredModel {
  id: string
  contextWindow?: number
  maxTokens?: number
  reasoning?: boolean
}

function parseJsonObject(
  value: unknown,
  label: string,
): Record<string, unknown> {
  try {
    return Value.Parse(JSON_RECORD, value)
  } catch {
    throw new Error(`${label} must be a JSON object`)
  }
}

function normalizeApi(value: string): CustomApi {
  const option = CUSTOM_API_OPTIONS.find((candidate) => candidate.value === value)
  if (!option) throw new Error(`Unsupported custom API protocol: ${value}`)
  return option.value
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

function normalizeModelId(raw: string): string {
  const value = raw.trim()
  if (!value) throw new Error('Model ID is required')
  if (value.length > 256) throw new Error('Model ID is too long')
  if (/[\u0000-\u001f\u007f]/.test(value)) {
    throw new Error('Model ID contains control characters')
  }
  return value
}

function normalizeApiKey(raw: string): string {
  const value = raw.trim()
  if (!value) throw new Error('API key is required')
  if (value.length > 8_192) throw new Error('API key is too long')
  if (/[\u0000-\u001f\u007f]/.test(value)) {
    throw new Error('API key contains control characters')
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
  const count = Math.round(Number(match[1]) * multiplier)
  if (!Number.isSafeInteger(count) || count <= 0) {
    throw new Error(`${label} must be a positive integer`)
  }
  return count
}

function normalizeTokenCount(value: number, label: string): number {
  if (!Number.isSafeInteger(value) || value <= 0) {
    throw new Error(`${label} must be a positive integer`)
  }
  return value
}

function positiveIntegerOrUndefined(value: unknown): number | undefined {
  return typeof value === 'number' &&
    Number.isSafeInteger(value) &&
    value > 0
    ? value
    : undefined
}

const MODEL_DISCOVERY_TIMEOUT_MS = 5_000

function resolveSecret(raw: string | undefined): string | undefined {
  if (!raw) return undefined
  const value = raw.trim()
  if (!value) return undefined
  if (value === '$$') return '$'
  if (value === '$!') return '!'
  if (value.startsWith('${') && value.endsWith('}')) {
    const name = value.slice(2, -1)
    return name ? process.env[name] || undefined : undefined
  }
  if (value.startsWith('$')) {
    const name = value.slice(1)
    return name ? process.env[name] || undefined : undefined
  }
  // Command-backed credentials are intentionally not run by discovery.
  if (value.startsWith('!')) return undefined
  return value
}

function readSavedApiKey(agentDir: string): string | undefined {
  const auth = readJsonObject(join(agentDir, 'auth.json'))
  const credential = readProvider(auth, 'auth.json custom')
  const credentialKey =
    typeof credential.key === 'string' ? credential.key : undefined
  if (credentialKey) return resolveSecret(credentialKey)

  const models = readJsonObject(join(agentDir, 'models.json'))
  const providers =
    models.providers === undefined
      ? {}
      : parseJsonObject(models.providers, 'models.json providers')
  const provider = readProvider(providers, 'models.json providers.custom')
  return typeof provider.apiKey === 'string'
    ? resolveSecret(provider.apiKey)
    : undefined
}

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
  const document = parseJsonObject(payload, 'model list response')
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
function recordReasoning(
  record: Record<string, unknown>,
): boolean | undefined {
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
  if (Array.isArray(supported)) {
    if (
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
    record = parseJsonObject(entry, 'model entry')
  } catch {
    return undefined
  }
  const rawId = typeof record.id === 'string' ? record.id : record.model
  if (typeof rawId !== 'string' || !rawId.trim()) return undefined
  const id = rawId.trim()
  const model: DiscoveredModel = { id }
  applyModelMetadata(record, model)
  return model
}

/** Unwrap a detail response; OpenAI returns the object directly, some gateways wrap it in `data`. */
function modelDetailRecord(payload: unknown): Record<string, unknown> | undefined {
  if (Array.isArray(payload)) return undefined
  let document: Record<string, unknown>
  try {
    document = parseJsonObject(payload, 'model detail response')
  } catch {
    return undefined
  }
  if (
    document.data !== undefined &&
    typeof document.data === 'object' &&
    document.data !== null &&
    !Array.isArray(document.data)
  ) {
    try {
      return parseJsonObject(document.data, 'model detail data')
    } catch {
      return undefined
    }
  }
  return document
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
      const unique = [...new Map(models.map((model) => [model.id, model])).values()]
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
  const reason = lastError instanceof Error ? lastError.message : String(lastError)
  throw new Error(reason || 'Model discovery failed')
}

function readJsonObject(path: string): Record<string, unknown> {
  const parsed = readJsonFileSync(path)
  return parsed === undefined ? {} : parseJsonObject(parsed, path)
}

function writeJson(
  path: string,
  value: Record<string, unknown>,
  mode?: number,
): void {
  atomicWriteSync(path, `${JSON.stringify(value, null, 2)}\n`, mode)
}

function readProvider(
  providers: Record<string, unknown>,
  label: string,
): Record<string, unknown> {
  const provider = providers[CUSTOM_PROVIDER_ID]
  return provider === undefined ? {} : parseJsonObject(provider, label)
}

function readModelEntries(
  provider: Record<string, unknown>,
  label: string,
): Record<string, unknown>[] {
  if (provider.models === undefined) return []
  if (!Array.isArray(provider.models)) {
    throw new Error(`${label}.models must be an array`)
  }
  return provider.models.map((entry, index) =>
    parseJsonObject(entry, `${label}.models[${index}]`),
  )
}

/** Read the custom provider without exposing its saved key. */
export function readCustomEndpoint(
  agentDir = getAgentDir(),
): ExistingEndpoint {
  const models = readJsonObject(join(agentDir, 'models.json'))
  const providers =
    models.providers === undefined
      ? {}
      : parseJsonObject(models.providers, 'models.json providers')
  const provider = readProvider(providers, 'models.json providers.custom')
  const model = readModelEntries(provider, 'models.json providers.custom').find(
    (entry) => entry.type === undefined || entry.type === 'chat',
  )

  const auth = readJsonObject(join(agentDir, 'auth.json'))
  const credential = readProvider(auth, 'auth.json custom')

  return {
    baseUrl:
      typeof provider.baseUrl === 'string' ? provider.baseUrl : undefined,
    api:
      typeof provider.api === 'string'
        ? CUSTOM_API_OPTIONS.find((option) => option.value === provider.api)
            ?.value
        : undefined,
    modelId: typeof model?.id === 'string' ? model.id : undefined,
    modelName: typeof model?.name === 'string' ? model.name : undefined,
    contextWindow: positiveIntegerOrUndefined(model?.contextWindow),
    maxTokens: positiveIntegerOrUndefined(model?.maxTokens),
    reasoning:
      typeof model?.reasoning === 'boolean' ? model.reasoning : undefined,
    hasKey:
      (credential.type === 'api_key' &&
        typeof credential.key === 'string' &&
        credential.key.length > 0) ||
      (typeof provider.apiKey === 'string' && provider.apiKey.length > 0),
  }
}

function buildModelEntry(
  api: CustomApi,
  modelId: string,
  modelName: string | undefined,
  previous: Record<string, unknown> | undefined,
  contextWindow: number | undefined,
  maxTokens: number | undefined,
  reasoning: boolean | undefined,
): Record<string, unknown> {
  const resolvedContextWindow =
    contextWindow ??
    positiveIntegerOrUndefined(previous?.contextWindow) ??
    DEFAULT_CONTEXT_WINDOW
  const resolvedMaxTokens =
    maxTokens ??
    positiveIntegerOrUndefined(previous?.maxTokens) ??
    DEFAULT_MAX_TOKENS
  if (resolvedMaxTokens > resolvedContextWindow) {
    throw new Error('Max output tokens cannot exceed the context window')
  }
  const resolvedReasoning =
    reasoning ??
    (typeof previous?.reasoning === 'boolean' ? previous.reasoning : false)
  const input =
    Array.isArray(previous?.input) &&
    previous.input.every((item) => item === 'text' || item === 'image')
      ? previous.input
      : ['text']

  const entry: Record<string, unknown> = {
    id: modelId,
    name:
      modelName ||
      (typeof previous?.name === 'string' && previous.name) ||
      modelId,
    reasoning: resolvedReasoning,
    input,
    cost: {
      input: 0,
      output: 0,
      cacheRead: 0,
      cacheWrite: 0,
    },
    contextWindow: resolvedContextWindow,
    maxTokens: resolvedMaxTokens,
  }

  // Conservative defaults for OpenAI-compatible proxies; users can refine
  // them in models.json when the endpoint supports more fields. Reasoning
  // effort stays auto-detected from the base URL once thinking is enabled,
  // because a fixed false would make the thinking levels a no-op.
  if (api === 'openai-completions') {
    entry.compat = {
      supportsStore: false,
      supportsDeveloperRole: false,
      supportsUsageInStreaming: false,
      maxTokensField: 'max_tokens',
      ...(resolvedReasoning ? {} : { supportsReasoningEffort: false }),
    }
  }
  return entry
}

/**
 * Persist a custom OpenAI/Anthropic-compatible provider.
 *
 * The endpoint and model metadata go to `models.json`; the secret goes to
 * `auth.json` only. Existing providers, credentials and model overrides are
 * preserved. Re-running the command updates the `custom` provider.
 */
export function saveCustomEndpoint(
  input: CustomEndpointInput,
  agentDir = getAgentDir(),
): SavedEndpoint {
  const baseUrl = normalizeBaseUrl(input.baseUrl)
  const api = normalizeApi(input.api)
  const modelId = normalizeModelId(input.modelId)
  const apiKey =
    input.apiKey === undefined ? undefined : normalizeApiKey(input.apiKey)
  const modelName = input.modelName?.trim() || undefined
  const contextWindow =
    input.contextWindow === undefined
      ? undefined
      : normalizeTokenCount(input.contextWindow, 'Context window')
  const maxTokens =
    input.maxTokens === undefined
      ? undefined
      : normalizeTokenCount(input.maxTokens, 'Max output tokens')

  const modelsPath = join(agentDir, 'models.json')
  const authPath = join(agentDir, 'auth.json')
  const models = readJsonObject(modelsPath)
  const auth = readJsonObject(authPath)

  const providers =
    models.providers === undefined
      ? {}
      : parseJsonObject(models.providers, 'models.json providers')
  const existingProvider = readProvider(
    providers,
    'models.json providers.custom',
  )
  const existingModels = readModelEntries(
    existingProvider,
    'models.json providers.custom',
  )
  const previous = existingModels.find(
    (entry) =>
      entry.id === modelId &&
      (entry.type === undefined || entry.type === 'chat'),
  )
  const nextModels = existingModels
    .filter(
      (entry) =>
        !(
          entry.id === modelId &&
          (entry.type === undefined || entry.type === 'chat')
        ),
    )
    .concat(
      buildModelEntry(
        api,
        modelId,
        modelName,
        previous,
        contextWindow,
        maxTokens,
        input.reasoning,
      ),
    )

  const nextProvider: Record<string, unknown> = {
    ...existingProvider,
    name:
      typeof existingProvider.name === 'string' &&
      existingProvider.name.trim()
        ? existingProvider.name
        : CUSTOM_PROVIDER_NAME,
    baseUrl,
    api,
    authHeader: api !== 'anthropic-messages',
    models: nextModels,
  }
  if (apiKey !== undefined) delete nextProvider.apiKey

  providers[CUSTOM_PROVIDER_ID] = nextProvider
  models.providers = providers
  if (typeof models.$schema !== 'string') models.$schema = MODELS_SCHEMA

  if (apiKey !== undefined) {
    auth[CUSTOM_PROVIDER_ID] = {
      type: 'api_key',
      key: apiKey,
    }
  }

  writeJson(modelsPath, models)
  if (apiKey !== undefined) writeJson(authPath, auth, 0o600)

  return { modelsPath, authPath, providerId: CUSTOM_PROVIDER_ID }
}

async function prompt(
  ctx: ExtensionCommandContext,
  title: string,
  placeholder: string,
): Promise<string | undefined> {
  return ctx.ui.input(title, placeholder)
}

/**
 * Register `/endpoint`, an interactive entry point for a custom URL, key and
 * model. Pi reads the same `models.json` and `auth.json` files after a restart,
 * so the configuration survives the session.
 */
export function registerEndpointCommand(pi: ExtensionAPI): void {
  pi.registerCommand('endpoint', {
    description:
      'Configure a custom API endpoint (URL, key, model) for the pi CLI',
    handler: async (_args, ctx) => {
      if (!ctx.hasUI) {
        ctx.ui.notify(
          'The /endpoint command needs an interactive terminal.',
          'error',
        )
        return
      }
      try {
        const agentDir = getAgentDir()
        const current = readCustomEndpoint(agentDir)

        const baseUrlInput = await prompt(
          ctx,
          'Custom API base URL (OpenAI/Anthropic-compatible)',
          current.baseUrl ?? 'https://api.example.com/v1',
        )
        if (baseUrlInput === undefined) return
        const baseUrlValue = baseUrlInput.trim() || current.baseUrl
        if (!baseUrlValue) throw new Error('API base URL is required')
        const baseUrl = normalizeBaseUrl(baseUrlValue)

        const apiOptions = [...CUSTOM_API_OPTIONS]
        if (current.api) {
          apiOptions.sort(
            (a, b) =>
              Number(b.value === current.api) - Number(a.value === current.api),
          )
        }
        const apiLabel = await ctx.ui.select(
          'API protocol',
          apiOptions.map((option) => option.label),
        )
        if (apiLabel === undefined) return
        const api =
          apiOptions.find((option) => option.label === apiLabel)?.value ??
          'openai-completions'

        const keyInput = await prompt(
          ctx,
          current.hasKey
            ? 'API key (Enter keeps the saved key; $ENV_VAR is supported)'
            : 'API key (or $ENV_VAR)',
          current.hasKey ? 'saved key' : 'sk-...',
        )
        if (keyInput === undefined) return
        const apiKey = keyInput.trim() || undefined
        if (!apiKey && !current.hasKey) throw new Error('API key is required')

        const discoveryKey =
          apiKey !== undefined
            ? resolveSecret(apiKey)
            : readSavedApiKey(agentDir)
        let discovered: DiscoveredModel[] = []
        if (discoveryKey) {
          try {
            discovered = await discoverModels(baseUrl, api, discoveryKey)
          } catch (error) {
            const message = error instanceof Error ? error.message : String(error)
            ctx.ui.notify(
              `Could not read /models (${message}); enter the model ID manually.`,
              'warning',
            )
          }
        } else if (apiKey !== undefined) {
          ctx.ui.notify(
            'API key reference could not be resolved; skipping model discovery.',
            'warning',
          )
        }

        const orderedModels = [...discovered]
        if (current.modelId) {
          orderedModels.sort(
            (a, b) =>
              Number(b.id === current.modelId) - Number(a.id === current.modelId),
          )
        }
        const manualModelLabel = 'Enter model ID manually…'
        let modelId: string | undefined
        let discoveredContext: number | undefined
        let discoveredMaxTokens: number | undefined
        let discoveredReasoning: boolean | undefined
        if (orderedModels.length > 0) {
          const selectedModel = await ctx.ui.select(
            'Model (from /models)',
            [
              ...orderedModels.map((model) => model.id),
              manualModelLabel,
            ],
          )
          if (selectedModel === undefined) return
          if (selectedModel !== manualModelLabel) {
            const model = orderedModels.find(
              (candidate) => candidate.id === selectedModel,
            )
            modelId = model?.id
            discoveredContext = model?.contextWindow
            discoveredMaxTokens = model?.maxTokens
            discoveredReasoning = model?.reasoning
          }
        }
        if (!modelId) {
          const modelInput = await prompt(
            ctx,
            'Model ID',
            current.modelId ?? 'gpt-4o-mini',
          )
          if (modelInput === undefined) return
          modelId = modelInput.trim() || current.modelId
        }
        if (!modelId) throw new Error('Model ID is required')

        const sameModel = current.modelId === modelId
        const reasoningDefault =
          discoveredReasoning ?? (sameModel ? current.reasoning : undefined) ?? false
        const thinkingOn = 'on — send thinking/reasoning parameters'
        const thinkingOff = 'off — no thinking parameters'
        const reasoningChoice = await ctx.ui.select(
          discoveredReasoning === undefined
            ? 'Thinking support'
            : `Thinking support (endpoint reports ${discoveredReasoning ? 'on' : 'off'})`,
          reasoningDefault ? [thinkingOn, thinkingOff] : [thinkingOff, thinkingOn],
        )
        if (reasoningChoice === undefined) return
        const reasoning = reasoningChoice === thinkingOn

        const contextDefault =
          discoveredContext ??
          (sameModel ? current.contextWindow : undefined) ??
          DEFAULT_CONTEXT_WINDOW
        const maxTokensDefault =
          discoveredMaxTokens ??
          (sameModel ? current.maxTokens : undefined) ??
          DEFAULT_MAX_TOKENS

        const contextInput = await prompt(
          ctx,
          'Context window in tokens (for example 128000 or 128k)',
          String(contextDefault),
        )
        if (contextInput === undefined) return
        const contextWindow = contextInput.trim()
          ? parseTokenCount(contextInput, 'Context window')
          : contextDefault

        const maxTokensInput = await prompt(
          ctx,
          'Max output tokens',
          String(maxTokensDefault),
        )
        if (maxTokensInput === undefined) return
        const maxTokens = maxTokensInput.trim()
          ? parseTokenCount(maxTokensInput, 'Max output tokens')
          : maxTokensDefault
        if (maxTokens > contextWindow) {
          throw new Error('Max output tokens cannot exceed the context window')
        }

        const saved = saveCustomEndpoint(
          {
            baseUrl,
            api,
            modelId,
            contextWindow,
            maxTokens,
            reasoning,
            apiKey,
          },
          agentDir,
        )
        await ctx.modelRegistry.refresh({ allowNetwork: false })

        const model = ctx.modelRegistry.find(CUSTOM_PROVIDER_ID, modelId)
        if (!model) {
          const reason = ctx.modelRegistry.getError()
          throw new Error(
            `Pi did not load ${CUSTOM_PROVIDER_ID}/${modelId}${
              reason ? `: ${reason}` : `; check ${saved.modelsPath}`
            }`,
          )
        }
        const auth = await ctx.modelRegistry.getApiKeyAndHeaders(model)
        if (!auth.ok) {
          throw new Error(
            `Saved the endpoint, but Pi cannot resolve the key: ${auth.error}`,
          )
        }

        let selected = false
        if (!ctx.model) {
          selected = await pi.setModel(model)
        }
        ctx.ui.notify(
          [
            `Saved ${CUSTOM_PROVIDER_ID}/${modelId}.`,
            `provider  ${baseUrl}`,
            `context   ${contextWindow} tokens`,
            `max out   ${maxTokens} tokens`,
            `thinking  ${reasoning ? 'on' : 'off'}`,
            selected
              ? 'selected as the current model'
              : 'run /model to select it',
            `key       ${apiKey ? 'saved in auth.json' : 'kept'}`,
          ].join('\n'),
          'info',
        )
      } catch (error) {
        const message = error instanceof Error ? error.message : String(error)
        ctx.ui.notify(`Custom endpoint failed: ${message}`, 'error')
      }
    },
  })
}
