/**
 * Shared Pi session construction for the sidecar's runtimes.
 *
 * Prompts, tools and conversation persistence vary by runtime; model settings,
 * the resource loader and the registered-tools check are shared.
 */

import {
  createAgentSession,
  createExtensionRuntime,
  ModelRuntime,
  type ResourceLoader,
  type LoadExtensionsResult,
  SessionManager,
  SettingsManager,
  type AgentSession,
  type Skill,
  type ToolDefinition,
} from '@earendil-works/pi-coding-agent'
import { InMemoryCredentialStore, InMemoryModelsStore, type Api, type Model } from '@earendil-works/pi-ai'

import type { AgentLlmConfig } from './llm.js'

/** One run's prompt and tool surface (chat vs Patent analysis). */
export interface SessionSpec {
  systemPrompt: string
  toolNames: readonly string[]
  customTools: readonly ToolDefinition[]
  skills?: readonly Skill[]
  sessionManager?: SessionManager
  extensions?: LoadExtensionsResult
}

export async function createConfiguredModel(config: AgentLlmConfig): Promise<{
  modelRuntime: ModelRuntime
  model: Model<Api>
}> {
  const modelRuntime = await ModelRuntime.create({
    credentials: new InMemoryCredentialStore(),
    modelsStore: new InMemoryModelsStore(),
    modelsPath: null,
    allowModelNetwork: false,
    refreshOnCreate: false,
  })
  const api: Api =
    config.provider === 'anthropic' ? 'anthropic-messages' : 'openai-completions'
  const providerName = 'mbforge-' + config.provider

  modelRuntime.registerProvider(providerName, {
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
        compat:
          api === 'openai-completions'
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

  const model = modelRuntime.getModel(providerName, config.model)
  if (!model) throw new Error('Could not register the configured LLM model')
  return { modelRuntime, model }
}

export async function createSessionForSpec(
  config: AgentLlmConfig,
  spec: SessionSpec,
): Promise<AgentSession> {
  const { modelRuntime, model } = await createConfiguredModel(config)
  const settingsManager = SettingsManager.inMemory({
    compaction: { enabled: false },
    retry: {
      enabled: false,
      provider: { timeoutMs: config.requestTimeoutMs, maxRetries: 0 },
    },
    defaultThinkingLevel: 'off',
  })
  const resourceLoader: ResourceLoader = {
    getExtensions: () => spec.extensions ?? ({
      extensions: [],
      errors: [],
      runtime: createExtensionRuntime(),
    }),
    getSkills: () => ({ skills: [...(spec.skills ?? [])], diagnostics: [] }),
    getPrompts: () => ({ prompts: [], diagnostics: [] }),
    getThemes: () => ({ themes: [], diagnostics: [] }),
    getAgentsFiles: () => ({ agentsFiles: [] }),
    getSystemPrompt: () => spec.systemPrompt,
    getSystemPromptSource: () => undefined,
    getAppendSystemPrompt: () => [],
    getAppendSystemPromptSources: () => [],
    extendResources: () => {},
    reload: async () => {},
  }

  const { session } = await createAgentSession({
    model,
    thinkingLevel: 'off',
    modelRuntime,
    noTools: 'builtin',
    settingsManager,
    resourceLoader,
    sessionManager: spec.sessionManager ?? SessionManager.inMemory(),
    tools: [...spec.toolNames],
    customTools: [...spec.customTools],
  })
  const registered = new Set(session.getAllTools().map((tool) => tool.name))
  const missing = spec.toolNames.filter((name) => !registered.has(name))
  if (missing.length > 0) {
    session.dispose()
    throw new Error('MBForge tools were not registered: ' + missing.join(', '))
  }
  return session
}
