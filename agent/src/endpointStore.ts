/**
 * Persistence for the pi CLI `custom` provider.
 *
 * Endpoint and model metadata live in `models.json`; the secret lives in
 * `auth.json` only. Every write preserves unrelated providers, credentials and
 * model overrides in both files.
 */

import { join } from 'node:path'

import { getAgentDir } from '@earendil-works/pi-coding-agent'

import {
  CUSTOM_PROVIDER_ID,
  DEFAULT_CONTEXT_WINDOW,
  DEFAULT_MAX_TOKENS,
  normalizeApi,
  normalizeApiKey,
  normalizeBaseUrl,
  normalizeModelId,
  normalizeTokenCount,
  readApi,
  resolveSecret,
  type CustomApi,
  type CustomEndpointInput,
  type ExistingEndpoint,
  type SavedEndpoint,
} from './endpointConfig.js'
import {
  parseJsonRecord,
  readJsonRecord,
  writeJsonRecord,
} from './localStore.js'

const CUSTOM_PROVIDER_NAME = 'Custom endpoint'
const MODELS_SCHEMA = 'https://pi.dev/schemas/models.schema.json'
const MODELS_LABEL = 'models.json providers.custom'
const AUTH_LABEL = 'auth.json custom'

function readProvider(
  record: Record<string, unknown>,
  label: string,
): Record<string, unknown> {
  const provider = record[CUSTOM_PROVIDER_ID]
  return provider === undefined ? {} : parseJsonRecord(provider, label)
}

function readCustomProvider(
  models: Record<string, unknown>,
): Record<string, unknown> {
  const providers =
    models.providers === undefined
      ? {}
      : parseJsonRecord(models.providers, 'models.json providers')
  return readProvider(providers, MODELS_LABEL)
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
    parseJsonRecord(entry, `${label}.models[${index}]`),
  )
}

function isChatEntry(entry: Record<string, unknown>): boolean {
  return entry.type === undefined || entry.type === 'chat'
}

function positiveIntegerOrUndefined(value: unknown): number | undefined {
  return typeof value === 'number' && Number.isSafeInteger(value) && value > 0
    ? value
    : undefined
}

/** Read the custom provider without exposing its saved key. */
export function readCustomEndpoint(agentDir = getAgentDir()): ExistingEndpoint {
  const provider = readCustomProvider(
    readJsonRecord(join(agentDir, 'models.json')),
  )
  const model = readModelEntries(provider, MODELS_LABEL).find(isChatEntry)
  const credential = readProvider(
    readJsonRecord(join(agentDir, 'auth.json')),
    AUTH_LABEL,
  )

  return {
    baseUrl:
      typeof provider.baseUrl === 'string' ? provider.baseUrl : undefined,
    api: readApi(provider.api),
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

/** Resolve the saved key for discovery; a `$ENV_VAR` reference may be unset. */
export function readSavedApiKey(agentDir: string): string | undefined {
  const credential = readProvider(
    readJsonRecord(join(agentDir, 'auth.json')),
    AUTH_LABEL,
  )
  if (typeof credential.key === 'string' && credential.key) {
    return resolveSecret(credential.key)
  }
  const provider = readCustomProvider(
    readJsonRecord(join(agentDir, 'models.json')),
  )
  return typeof provider.apiKey === 'string'
    ? resolveSecret(provider.apiKey)
    : undefined
}

interface ModelEntryInput {
  api: CustomApi
  modelId: string
  modelName?: string
  previous?: Record<string, unknown>
  contextWindow?: number
  maxTokens?: number
  reasoning?: boolean
}

function buildModelEntry(input: ModelEntryInput): Record<string, unknown> {
  const { api, modelId, modelName, previous } = input
  const contextWindow =
    input.contextWindow ??
    positiveIntegerOrUndefined(previous?.contextWindow) ??
    DEFAULT_CONTEXT_WINDOW
  const maxTokens =
    input.maxTokens ??
    positiveIntegerOrUndefined(previous?.maxTokens) ??
    DEFAULT_MAX_TOKENS
  if (maxTokens > contextWindow) {
    throw new Error('Max output tokens cannot exceed the context window')
  }
  const reasoning =
    input.reasoning ??
    (typeof previous?.reasoning === 'boolean' ? previous.reasoning : false)
  const modalities =
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
    reasoning,
    input: modalities,
    cost: {
      input: 0,
      output: 0,
      cacheRead: 0,
      cacheWrite: 0,
    },
    contextWindow,
    maxTokens,
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
      ...(reasoning ? {} : { supportsReasoningEffort: false }),
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
  const models = readJsonRecord(modelsPath)
  const auth = readJsonRecord(authPath)

  const providers =
    models.providers === undefined
      ? {}
      : parseJsonRecord(models.providers, 'models.json providers')
  const existingProvider = readProvider(providers, MODELS_LABEL)
  const existingModels = readModelEntries(existingProvider, MODELS_LABEL)
  const previous = existingModels.find(
    (entry) => entry.id === modelId && isChatEntry(entry),
  )
  const nextModels = existingModels
    .filter((entry) => !(entry.id === modelId && isChatEntry(entry)))
    .concat(
      buildModelEntry({
        api,
        modelId,
        modelName: input.modelName?.trim() || undefined,
        previous,
        contextWindow,
        maxTokens,
        reasoning: input.reasoning,
      }),
    )

  const nextProvider: Record<string, unknown> = {
    ...existingProvider,
    name:
      typeof existingProvider.name === 'string' && existingProvider.name.trim()
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

  writeJsonRecord(modelsPath, models)
  if (apiKey !== undefined) writeJsonRecord(authPath, auth, 0o600)

  return { modelsPath, authPath, providerId: CUSTOM_PROVIDER_ID }
}
