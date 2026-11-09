import { readFile } from 'node:fs/promises'
import { homedir } from 'node:os'
import { join } from 'node:path'

import {
  AuthStorage,
  createAgentSession,
  createExtensionRuntime,
  ModelRegistry,
  type ResourceLoader,
  SessionManager,
  SettingsManager,
  type AgentSession,
} from '@mariozechner/pi-coding-agent'
import type { Api, Model } from '@mariozechner/pi-ai'

import { loadCapabilityTools, type AgentMode } from './capabilities.js'

export interface AgentLlmConfig {
  provider: string
  model: string
  apiKey: string
  baseUrl: string
  maxTokens: number
  requestTimeoutMs: number
}

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

function defaultBaseUrl(provider: string): string {
  if (provider === 'deepseek') return 'https://api.deepseek.com/v1'
  if (provider === 'ollama') return 'http://127.0.0.1:11434/v1'
  if (provider === 'anthropic') return 'https://api.anthropic.com'
  return 'https://api.openai.com/v1'
}

async function loadPersistedLlmConfig(): Promise<Record<string, unknown>> {
  const settingsPath = process.env.MBFORGE_SETTINGS_PATH
    ?? join(homedir(), 'MBForge', 'settings.json')
  try {
    const parsed = JSON.parse(await readFile(settingsPath, 'utf8')) as unknown
    return asRecord(asRecord(parsed).llm)
  } catch {
    return {}
  }
}

function mergeConfig(raw: unknown, persisted: Record<string, unknown>): Record<string, unknown> {
  const value = asRecord(raw)
  const merged = { ...persisted }
  for (const [key, candidate] of Object.entries(value)) {
    if (candidate !== '' && candidate !== '***') merged[key] = candidate
  }
  return merged
}

export function readConfig(raw: unknown, persisted: Record<string, unknown>): AgentLlmConfig {
  const value = mergeConfig(raw, persisted)
  const provider = stringValue(
    value.provider ?? process.env.MBFORGE_AGENT_PROVIDER,
    'openai_compatible',
    80,
  ).toLowerCase()
  const apiKey = stringValue(
    value.api_key ?? value.apiKey ?? process.env.MBFORGE_AGENT_API_KEY,
    provider === 'ollama' ? 'ollama' : '',
    4096,
  )
  const model = stringValue(
    value.model ?? process.env.MBFORGE_AGENT_MODEL,
    'gpt-4o-mini',
    256,
  )
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

function createConfiguredModel(config: AgentLlmConfig): {
  authStorage: AuthStorage
  modelRegistry: ModelRegistry
  model: Model<Api>
} {
  const authStorage = AuthStorage.inMemory()
  const modelRegistry = ModelRegistry.inMemory(authStorage)
  const api: Api = config.provider === 'anthropic' ? 'anthropic-messages' : 'openai-completions'
  const providerName = `mbforge-${config.provider}`

  modelRegistry.registerProvider(providerName, {
    name: config.provider,
    api,
    baseUrl: config.baseUrl,
    apiKey: config.apiKey,
    authHeader: api === 'openai-completions',
    models: [
      {
        id: config.model,
        name: config.model,
        api,
        reasoning: false,
        input: ['text'],
        cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
        contextWindow: 131072,
        maxTokens: config.maxTokens,
        compat: api === 'openai-completions'
          ? {
              supportsStore: false,
              supportsDeveloperRole: false,
              supportsReasoningEffort: false,
              supportsUsageInStreaming: false,
              maxTokensField: 'max_tokens',
            }
          : undefined,
      },
    ],
  })

  const model = modelRegistry.find(providerName, config.model)
  if (!model) throw new Error('Could not register the configured LLM model')
  return { authStorage, modelRegistry, model }
}

export async function readPersistedConfig(raw: unknown): Promise<AgentLlmConfig> {
  return readConfig(raw, await loadPersistedLlmConfig())
}

export async function createSession(
  config: AgentLlmConfig,
  mode: AgentMode,
): Promise<AgentSession> {
  const { authStorage, modelRegistry, model } = createConfiguredModel(config)
  const settingsManager = SettingsManager.inMemory({
    compaction: { enabled: false },
    retry: {
      enabled: false,
      provider: { timeoutMs: config.requestTimeoutMs, maxRetries: 0 },
    },
    defaultThinkingLevel: 'off',
  })
  const capabilityTools = await loadCapabilityTools(mode)
  const resourceLoader: ResourceLoader = {
    getExtensions: () => ({ extensions: [], errors: [], runtime: createExtensionRuntime() }),
    getSkills: () => ({ skills: [], diagnostics: [] }),
    getPrompts: () => ({ prompts: [], diagnostics: [] }),
    getThemes: () => ({ themes: [], diagnostics: [] }),
    getAgentsFiles: () => ({ agentsFiles: [] }),
    getSystemPrompt: () =>
      'You are the MBForge molecular-science assistant. ' +
      `You are in ${mode} mode. ` +
      (mode === 'edit'
        ? 'Mutating capabilities are available; use them only when the task requires changing library state. '
        : 'Only read-only capabilities are available; never attempt to change library state. ') +
      'Search the library before making claims. Separate source-backed facts from hypotheses, ' +
      'cite returned identifiers, and never claim a search result is a validated design recommendation.',
    getAppendSystemPrompt: () => [],
    extendResources: () => {},
    reload: async () => {},
  }

  const { session } = await createAgentSession({
    model,
    thinkingLevel: 'off',
    authStorage,
    modelRegistry,
    settingsManager,
    resourceLoader,
    sessionManager: SessionManager.inMemory(),
    tools: capabilityTools.map((tool) => tool.name),
    customTools: capabilityTools,
  })
  if (!session.getAllTools().some((tool) => tool.name === 'resolve_document')) {
    session.dispose()
    throw new Error('MBForge capability tools were not registered')
  }
  return session
}
