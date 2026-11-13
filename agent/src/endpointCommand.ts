/**
 * `/endpoint` — interactive configuration for a custom OpenAI- or
 * Anthropic-compatible API endpoint. Pi reads the same `models.json` and
 * `auth.json` files after a restart, so the configuration survives the session.
 */

import {
  getAgentDir,
  type ExtensionAPI,
  type ExtensionCommandContext,
} from '@earendil-works/pi-coding-agent'

import {
  CUSTOM_API_OPTIONS,
  CUSTOM_PROVIDER_ID,
  DEFAULT_CONTEXT_WINDOW,
  DEFAULT_MAX_TOKENS,
  normalizeBaseUrl,
  parseTokenCount,
  resolveSecret,
  type CustomApi,
  type ExistingEndpoint,
  type SavedEndpoint,
} from './endpointConfig.js'
import { discoverModels, type DiscoveredModel } from './endpointDiscovery.js'
import {
  readCustomEndpoint,
  readSavedApiKey,
  saveCustomEndpoint,
} from './endpointStore.js'
import { errorMessage } from './text.js'

const MANUAL_MODEL = 'Enter model ID manually…'
const THINKING_ON = 'on — send thinking/reasoning parameters'
const THINKING_OFF = 'off — no thinking parameters'

/** Copy items so that the one matching `isCurrent` comes first. */
function withCurrentFirst<T>(
  items: readonly T[],
  isCurrent: (item: T) => boolean,
): T[] {
  const index = items.findIndex(isCurrent)
  if (index <= 0) return [...items]
  return [items[index], ...items.slice(0, index), ...items.slice(index + 1)]
}

async function askBaseUrl(
  ctx: ExtensionCommandContext,
  current: ExistingEndpoint,
): Promise<string | undefined> {
  const input = await ctx.ui.input(
    'Custom API base URL (OpenAI/Anthropic-compatible)',
    current.baseUrl ?? 'https://api.example.com/v1',
  )
  if (input === undefined) return undefined
  const value = input.trim() || current.baseUrl
  if (!value) throw new Error('API base URL is required')
  return normalizeBaseUrl(value)
}

async function askApi(
  ctx: ExtensionCommandContext,
  current: ExistingEndpoint,
): Promise<CustomApi | undefined> {
  const options = current.api
    ? withCurrentFirst(
        CUSTOM_API_OPTIONS,
        (option) => option.value === current.api,
      )
    : [...CUSTOM_API_OPTIONS]
  const label = await ctx.ui.select(
    'API protocol',
    options.map((option) => option.label),
  )
  if (label === undefined) return undefined
  return (
    options.find((option) => option.label === label)?.value ??
    'openai-completions'
  )
}

/**
 * Prompt for the key. An empty answer keeps the saved key, so `apiKey`
 * stays undefined and only a non-empty input is persisted.
 */
async function askKey(
  ctx: ExtensionCommandContext,
  current: ExistingEndpoint,
): Promise<{ apiKey?: string } | undefined> {
  const input = await ctx.ui.input(
    current.hasKey
      ? 'API key (Enter keeps the saved key; $ENV_VAR is supported)'
      : 'API key (or $ENV_VAR)',
    current.hasKey ? 'saved key' : 'sk-...',
  )
  if (input === undefined) return undefined
  const apiKey = input.trim() || undefined
  if (!apiKey && !current.hasKey) throw new Error('API key is required')
  return { apiKey }
}

/** Discover models, downgrading every failure to a warning and an empty list. */
async function discoverOrWarn(
  ctx: ExtensionCommandContext,
  baseUrl: string,
  api: CustomApi,
  apiKey: string | undefined,
  agentDir: string,
): Promise<DiscoveredModel[]> {
  const key =
    apiKey !== undefined ? resolveSecret(apiKey) : readSavedApiKey(agentDir)
  if (key) {
    try {
      return await discoverModels(baseUrl, api, key)
    } catch (error) {
      const reason = errorMessage(error)
      ctx.ui.notify(
        `Could not read /models (${reason}); enter the model ID manually.`,
        'warning',
      )
    }
  } else if (apiKey !== undefined) {
    ctx.ui.notify(
      'API key reference could not be resolved; skipping model discovery.',
      'warning',
    )
  }
  return []
}

interface ModelChoice {
  modelId: string
  contextWindow?: number
  maxTokens?: number
  reasoning?: boolean
}

async function askModel(
  ctx: ExtensionCommandContext,
  discovered: DiscoveredModel[],
  current: ExistingEndpoint,
): Promise<ModelChoice | undefined> {
  const models = current.modelId
    ? withCurrentFirst(discovered, (model) => model.id === current.modelId)
    : discovered
  if (models.length > 0) {
    const selected = await ctx.ui.select('Model (from /models)', [
      ...models.map((model) => model.id),
      MANUAL_MODEL,
    ])
    if (selected === undefined) return undefined
    const model = models.find((candidate) => candidate.id === selected)
    if (model) {
      return {
        modelId: model.id,
        contextWindow: model.contextWindow,
        maxTokens: model.maxTokens,
        reasoning: model.reasoning,
      }
    }
  }

  const input = await ctx.ui.input('Model ID', current.modelId ?? 'gpt-4o-mini')
  if (input === undefined) return undefined
  const modelId = input.trim() || current.modelId
  if (!modelId) throw new Error('Model ID is required')
  return { modelId }
}

async function askReasoning(
  ctx: ExtensionCommandContext,
  current: ExistingEndpoint,
  sameModel: boolean,
  reported: boolean | undefined,
): Promise<boolean | undefined> {
  const fallback =
    reported ?? (sameModel ? current.reasoning : undefined) ?? false
  const choice = await ctx.ui.select(
    reported === undefined
      ? 'Thinking support'
      : `Thinking support (endpoint reports ${reported ? 'on' : 'off'})`,
    fallback ? [THINKING_ON, THINKING_OFF] : [THINKING_OFF, THINKING_ON],
  )
  if (choice === undefined) return undefined
  return choice === THINKING_ON
}

interface TokenLimits {
  contextWindow: number
  maxTokens: number
}

async function askLimits(
  ctx: ExtensionCommandContext,
  defaults: TokenLimits,
): Promise<TokenLimits | undefined> {
  const contextInput = await ctx.ui.input(
    'Context window in tokens (for example 128000 or 128k)',
    String(defaults.contextWindow),
  )
  if (contextInput === undefined) return undefined
  const contextWindow = contextInput.trim()
    ? parseTokenCount(contextInput, 'Context window')
    : defaults.contextWindow

  const maxTokensInput = await ctx.ui.input(
    'Max output tokens',
    String(defaults.maxTokens),
  )
  if (maxTokensInput === undefined) return undefined
  const maxTokens = maxTokensInput.trim()
    ? parseTokenCount(maxTokensInput, 'Max output tokens')
    : defaults.maxTokens
  if (maxTokens > contextWindow) {
    throw new Error('Max output tokens cannot exceed the context window')
  }
  return { contextWindow, maxTokens }
}

/** Reload models.json, verify pi can resolve the new model, then select it. */
async function activateSavedModel(
  ctx: ExtensionCommandContext,
  pi: ExtensionAPI,
  saved: SavedEndpoint,
  modelId: string,
  summary: TokenLimits & {
    baseUrl: string
    reasoning: boolean
    apiKey: string | undefined
  },
): Promise<void> {
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

  const selected = ctx.model ? false : await pi.setModel(model)
  ctx.ui.notify(
    [
      `Saved ${CUSTOM_PROVIDER_ID}/${modelId}.`,
      `provider  ${summary.baseUrl}`,
      `context   ${summary.contextWindow} tokens`,
      `max out   ${summary.maxTokens} tokens`,
      `thinking  ${summary.reasoning ? 'on' : 'off'}`,
      selected ? 'selected as the current model' : 'run /model to select it',
      `key       ${summary.apiKey ? 'saved in auth.json' : 'kept'}`,
    ].join('\n'),
    'info',
  )
}

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

        const baseUrl = await askBaseUrl(ctx, current)
        if (!baseUrl) return
        const api = await askApi(ctx, current)
        if (!api) return
        const key = await askKey(ctx, current)
        if (!key) return

        const discovered = await discoverOrWarn(
          ctx,
          baseUrl,
          api,
          key.apiKey,
          agentDir,
        )
        const chosen = await askModel(ctx, discovered, current)
        if (!chosen) return

        const sameModel = current.modelId === chosen.modelId
        const reasoning = await askReasoning(
          ctx,
          current,
          sameModel,
          chosen.reasoning,
        )
        if (reasoning === undefined) return

        const limits = await askLimits(ctx, {
          contextWindow:
            chosen.contextWindow ??
            (sameModel ? current.contextWindow : undefined) ??
            DEFAULT_CONTEXT_WINDOW,
          maxTokens:
            chosen.maxTokens ??
            (sameModel ? current.maxTokens : undefined) ??
            DEFAULT_MAX_TOKENS,
        })
        if (!limits) return

        const saved = saveCustomEndpoint(
          {
            baseUrl,
            api,
            modelId: chosen.modelId,
            contextWindow: limits.contextWindow,
            maxTokens: limits.maxTokens,
            reasoning,
            apiKey: key.apiKey,
          },
          agentDir,
        )
        await activateSavedModel(ctx, pi, saved, chosen.modelId, {
          baseUrl,
          ...limits,
          reasoning,
          apiKey: key.apiKey,
        })
      } catch (error) {
        const message = errorMessage(error)
        ctx.ui.notify(`Custom endpoint failed: ${message}`, 'error')
      }
    },
  })
}
