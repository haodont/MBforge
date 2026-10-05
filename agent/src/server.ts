import { randomUUID } from 'node:crypto'
import { createServer, type IncomingMessage, type ServerResponse } from 'node:http'

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

import {
  asRecord,
  fetchProviderModels,
  loadPersistedLlmConfig,
  probeLlm,
  readConfig,
  resolveProviderTarget,
  sanitizeError,
  settingsPath,
  stringValue,
  type AgentLlmConfig,
  type LlmProbeResult,
} from './llm.js'
import { moleculeSearchTool } from './tool.js'

interface ChatRequest {
  message: string
  session_id?: string
  config?: Partial<AgentLlmConfig> & { api_key?: string; max_tokens?: number; request_timeout?: number }
}

interface SessionEntry {
  config: AgentLlmConfig
  signature: string
  session: AgentSession
  tail: Promise<void>
}

const sessions = new Map<string, SessionEntry>()
const maxSessions = 32

function createConfiguredModel(config: AgentLlmConfig): {
  authStorage: AuthStorage
  modelRegistry: ModelRegistry
  model: Model<Api>
} {
  const authStorage = AuthStorage.inMemory()
  const modelRegistry = ModelRegistry.inMemory(authStorage)
  const api: Api = config.provider === 'anthropic' ? 'anthropic-messages' : 'openai-completions'
  const providerName = 'mbforge-' + config.provider

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

async function createSession(config: AgentLlmConfig): Promise<AgentSession> {
  const { authStorage, modelRegistry, model } = createConfiguredModel(config)
  const settingsManager = SettingsManager.inMemory({
    compaction: { enabled: false },
    retry: { enabled: false, provider: { timeoutMs: config.requestTimeoutMs, maxRetries: 0 } },
    defaultThinkingLevel: 'off',
  })
  const resourceLoader: ResourceLoader = {
    getExtensions: () => ({ extensions: [], errors: [], runtime: createExtensionRuntime() }),
    getSkills: () => ({ skills: [], diagnostics: [] }),
    getPrompts: () => ({ prompts: [], diagnostics: [] }),
    getThemes: () => ({ themes: [], diagnostics: [] }),
    getAgentsFiles: () => ({ agentsFiles: [] }),
    getSystemPrompt: () =>
      'You are the MBForge molecular-science assistant. Use molecule_search for library facts. ' +
      'Separate source-backed facts from hypotheses, cite returned molecule identifiers when relevant, ' +
      'and never claim that a search result is a validated design recommendation.',
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
    tools: ['molecule_search'],
    customTools: [moleculeSearchTool],
  })
  if (!session.getAllTools().some((tool) => tool.name === 'molecule_search')) {
    session.dispose()
    throw new Error('MBForge molecule_search tool was not registered')
  }
  return session
}

async function getSession(sessionId: string, config: AgentLlmConfig): Promise<SessionEntry> {
  const signature = JSON.stringify(config)
  const existing = sessions.get(sessionId)
  if (existing && existing.signature === signature) return existing
  existing?.session.dispose()

  const session = await createSession(config)
  const entry: SessionEntry = { config, signature, session, tail: Promise.resolve() }
  sessions.set(sessionId, entry)
  while (sessions.size > maxSessions) {
    const oldest = sessions.keys().next().value
    if (!oldest) break
    const evicted = sessions.get(oldest)
    evicted?.session.dispose()
    sessions.delete(oldest)
  }
  return entry
}

function corsOrigin(request: IncomingMessage): string {
  const origin = request.headers.origin
  if (!origin) return '*'
  const frontendPort = process.env.MBFORGE_FRONTEND_PORT ?? '5173'
  const backendPort = process.env.MBFORGE_BACKEND_PORT ?? '18792'
  const allowed = new Set([
    'http://127.0.0.1:' + frontendPort,
    'http://localhost:' + frontendPort,
    'http://127.0.0.1:' + backendPort,
    'http://localhost:' + backendPort,
  ])
  return allowed.has(origin) ? origin : 'null'
}

function commonHeaders(request: IncomingMessage): Record<string, string> {
  return {
    'access-control-allow-origin': corsOrigin(request),
    'access-control-allow-headers': 'content-type',
    'access-control-allow-methods': 'GET,POST,OPTIONS',
    vary: 'origin',
  }
}

function sendJson(request: IncomingMessage, response: ServerResponse, status: number, body: unknown): void {
  response.writeHead(status, { ...commonHeaders(request), 'content-type': 'application/json; charset=utf-8' })
  response.end(JSON.stringify(body))
}

function writeSse(response: ServerResponse, event: string, body: unknown): void {
  if (response.writableEnded) return
  response.write('event: ' + event + '\ndata: ' + JSON.stringify(body) + '\n\n')
}

async function readBody(request: IncomingMessage): Promise<unknown> {
  const chunks: Buffer[] = []
  let length = 0
  for await (const chunk of request) {
    const buffer = Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk)
    length += buffer.length
    if (length > 512 * 1024) throw new Error('request body is too large')
    chunks.push(buffer)
  }
  return JSON.parse(Buffer.concat(chunks).toString('utf8'))
}

async function handleChat(request: IncomingMessage, response: ServerResponse, body: unknown): Promise<void> {
  const input = asRecord(body) as unknown as ChatRequest
  const message = typeof input.message === 'string' ? input.message.trim() : ''
  if (!message || message.length > 20000) {
    sendJson(request, response, 422, { error: 'message must contain 1-20000 characters' })
    return
  }

  const sessionId = stringValue(input.session_id, randomUUID(), 128)
  const existing = sessions.get(sessionId)
  const config = readConfig(
    input.config ?? existing?.config,
    await loadPersistedLlmConfig(),
  )
  const entry = await getSession(sessionId, config)

  response.writeHead(200, {
    ...commonHeaders(request),
    'content-type': 'text/event-stream; charset=utf-8',
    'cache-control': 'no-cache, no-transform',
    connection: 'keep-alive',
  })

  const run = entry.tail.then(async () => {
    let text = ''
    let closed = false
    const onClose = () => {
      closed = true
      if (entry.session.isStreaming) void entry.session.abort()
    }
    response.once('close', onClose)
    const unsubscribe = entry.session.subscribe((event) => {
      if (closed) return
      if (event.type === 'message_update' && event.assistantMessageEvent.type === 'text_delta') {
        text += event.assistantMessageEvent.delta
        writeSse(response, 'delta', { text: event.assistantMessageEvent.delta })
      } else if (event.type === 'tool_execution_start') {
        writeSse(response, 'tool', { name: event.toolName, status: 'start' })
      } else if (event.type === 'tool_execution_end') {
        writeSse(response, 'tool', { name: event.toolName, status: event.isError ? 'error' : 'done' })
      }
    })

    try {
      await entry.session.prompt(message, { expandPromptTemplates: false, source: 'rpc' })
      const errorMessage = entry.session.agent.state.errorMessage
      if (errorMessage) writeSse(response, 'error', { message: errorMessage })
      else writeSse(response, 'done', { session_id: sessionId, text })
    } catch (error) {
      const detail = error instanceof Error ? error.message : String(error)
      writeSse(response, 'error', { message: detail })
    } finally {
      unsubscribe()
      response.removeListener('close', onClose)
      if (!response.writableEnded) response.end()
    }
  })
  entry.tail = run.catch(() => undefined)
  await run
}

/** Provider model-list probe. Business failures stay HTTP 200 with success:
 *  false, matching the backend endpoint this replaced, so the Settings UI can
 *  show the provider's own reason verbatim. */
async function handleModels(request: IncomingMessage, response: ServerResponse, body: unknown): Promise<void> {
  const input = asRecord(body)
  try {
    // Lenient resolution: listing models must work for a keyless local gateway.
    const target = resolveProviderTarget(input, await loadPersistedLlmConfig())
    const models = await fetchProviderModels(target.provider, target.baseUrl, target.apiKey)
    sendJson(request, response, 200, { success: true, models })
  } catch (error) {
    sendJson(request, response, 200, { success: false, error: sanitizeError(error, input.api_key) })
  }
}

/** Connectivity probe: one token against the configured endpoint. Always 200 so
 *  the UI renders the reason instead of a transport error. */
async function handleProbe(request: IncomingMessage, response: ServerResponse, body: unknown): Promise<void> {
  const input = asRecord(body)
  let result: LlmProbeResult
  try {
    result = await probeLlm(await readConfigAsync(input))
  } catch (error) {
    result = {
      ok: false,
      latency_ms: null,
      error: sanitizeError(error, input.api_key),
      provider: stringValue(input.provider, '', 80),
      model: stringValue(input.model, '', 256),
    }
  }
  sendJson(request, response, 200, result)
}

async function readConfigAsync(input: Record<string, unknown>): Promise<AgentLlmConfig> {
  return readConfig(input, await loadPersistedLlmConfig())
}

async function handleRequest(request: IncomingMessage, response: ServerResponse): Promise<void> {
  if (request.method === 'OPTIONS') {
    response.writeHead(204, commonHeaders(request))
    response.end()
    return
  }
  if (request.url === '/health' && request.method === 'GET') {
    sendJson(request, response, 200, { ok: true, runtime: 'pi', settings_path: settingsPath() })
    return
  }
  if (request.method !== 'POST') {
    sendJson(request, response, 404, { error: 'not found' })
    return
  }

  let body: unknown
  try {
    body = await readBody(request)
  } catch (error) {
    sendJson(request, response, 400, { error: sanitizeError(error, '') })
    return
  }

  try {
    if (request.url === '/v1/chat') await handleChat(request, response, body)
    else if (request.url === '/v1/models') await handleModels(request, response, body)
    else if (request.url === '/v1/probe') await handleProbe(request, response, body)
    else sendJson(request, response, 404, { error: 'not found' })
  } catch (error) {
    const detail = sanitizeError(error, '')
    if (!response.headersSent) sendJson(request, response, 400, { error: detail })
    else if (!response.writableEnded) response.end()
  }
}

const host = process.env.MBFORGE_AGENT_HOST ?? '127.0.0.1'
const port = Number(process.env.MBFORGE_AGENT_PORT ?? 18800)
if (!Number.isInteger(port) || port < 1 || port > 65535) {
  throw new Error('MBFORGE_AGENT_PORT must be an integer between 1 and 65535')
}

createServer((request, response) => {
  void handleRequest(request, response)
}).listen(port, host, () => {
  console.log('MBForge Pi agent listening on http://' + host + ':' + port)
})
