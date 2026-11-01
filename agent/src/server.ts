import { randomUUID } from 'node:crypto'
import { createServer, type IncomingMessage, type ServerResponse } from 'node:http'

import type { AgentSession } from '@earendil-works/pi-coding-agent'

import { commonHeaders, readBody, sendJson, startSse, writeSse } from './http.js'
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
import { createSessionForSpec, type SessionSpec } from './session.js'
import { handleResearchChat, handleResearchStatus } from './research.js'
import { researchPrompt } from './prompts.js'
import { createWebTools, loadWebConfig } from './web.js'
import { loadSkillTool, researchSkills } from './skills.js'
import {
  handlePatentAnalysis,
  handlePatentAnalysisCancel,
} from './patent-analysis.js'
import {
  librarySqlTool,
  libraryStatsTool,
  moleculeSearchTool,
  queryActivitiesTool,
  queryDocumentsTool,
  queryEvidenceTool,
  searchLibraryTool,
} from './tool.js'

/** The chat custom tools, and the allow-list passed to the session. Kept
 *  together so the two never drift. */
const AGENT_TOOL_NAMES = [
  'molecule_search',
  'library_stats',
  'query_documents',
  'query_activities',
  'query_evidence',
  'search_library',
  'load_skill',
  'library_sql',
] as const

const AGENT_CUSTOM_TOOLS = [
  moleculeSearchTool,
  libraryStatsTool,
  queryDocumentsTool,
  queryActivitiesTool,
  queryEvidenceTool,
  searchLibraryTool,
  loadSkillTool,
  librarySqlTool,
]

const CHAT_SYSTEM_PROMPT =
  'You are the MBForge molecular-science assistant. Use molecule_search for ' +
  'molecule lookups, and the library tools (library_stats, query_documents, ' +
  'query_activities, query_evidence) for structured library facts; use ' +
  'library_sql (read-only SELECT) only for questions the structured tools do ' +
  'not cover. ' +
  'Separate source-backed facts from hypotheses, cite returned molecule ' +
  'identifiers when relevant, and never claim that a search result is a ' +
  'validated design recommendation.'

/** The chat run's prompt and tool surface (the Patent run has its own). */
const CHAT_SPEC: SessionSpec = {
  systemPrompt: CHAT_SYSTEM_PROMPT,
  toolNames: AGENT_TOOL_NAMES,
  customTools: AGENT_CUSTOM_TOOLS,
}

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
  resetWeb: (message: string) => void
}

const sessions = new Map<string, SessionEntry>()
const maxSessions = 32

async function getSession(sessionId: string, config: AgentLlmConfig): Promise<SessionEntry> {
  const webConfig = await loadWebConfig()
  const signature = JSON.stringify({ config, webConfig })
  const existing = sessions.get(sessionId)
  if (existing && existing.signature === signature) return existing
  existing?.session.dispose()

  const web = await createWebTools(webConfig)
  const session = await createSessionForSpec(config, {
    ...CHAT_SPEC, systemPrompt: researchPrompt(web.toolNames.length > 0) + '\n' + CHAT_SYSTEM_PROMPT,
    toolNames: [...AGENT_TOOL_NAMES, ...web.toolNames], extensions: web.extensions,
    skills: researchSkills,
  })
  const entry: SessionEntry = { config, signature, session, tail: Promise.resolve(), resetWeb: web.reset }
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

  startSse(request, response)

  const run = entry.tail.then(async () => {
    entry.resetWeb(message)
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
      if (errorMessage) writeSse(response, 'error', { message: sanitizeError(errorMessage, config.apiKey) })
      else writeSse(response, 'done', { session_id: sessionId, text })
    } catch (error) {
      const detail = error instanceof Error ? error.message : String(error)
      writeSse(response, 'error', { message: sanitizeError(detail, config.apiKey) })
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
    else if (request.url === '/v1/research-chat') await handleResearchChat(request, response, body)
    else if (request.url === '/v1/research-status') handleResearchStatus(request, response, body)
    else if (request.url === '/v1/patent-analysis') {
      await handlePatentAnalysis(request, response, body)
    } else if (request.url === '/v1/patent-analysis/cancel') {
      await handlePatentAnalysisCancel(request, response, body)
    } else if (request.url === '/v1/models') await handleModels(request, response, body)
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
