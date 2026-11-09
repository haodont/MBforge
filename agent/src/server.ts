import { randomUUID } from 'node:crypto'
import { createServer, type IncomingMessage, type ServerResponse } from 'node:http'

import type { AgentSession } from '@mariozechner/pi-coding-agent'

import { createSession, readPersistedConfig, type AgentLlmConfig } from './runtime.js'

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

function asRecord(value: unknown): Record<string, unknown> {
  return typeof value === 'object' && value !== null ? value as Record<string, unknown> : {}
}

function stringValue(value: unknown, fallback: string, maxLength = 512): string {
  if (typeof value !== 'string') return fallback
  const trimmed = value.trim()
  return trimmed.length > 0 && trimmed.length <= maxLength ? trimmed : fallback
}

async function getSession(sessionId: string, config: AgentLlmConfig): Promise<SessionEntry> {
  const signature = JSON.stringify(config)
  const existing = sessions.get(sessionId)
  if (existing && existing.signature === signature) return existing
  existing?.session.dispose()

  const mode = process.env.MBFORGE_AGENT_MODE === 'edit' ? 'edit' : 'readonly'
  const session = await createSession(config, mode)
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
    `http://127.0.0.1:${frontendPort}`,
    `http://localhost:${frontendPort}`,
    `http://127.0.0.1:${backendPort}`,
    `http://localhost:${backendPort}`,
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
  response.write(`event: ${event}\ndata: ${JSON.stringify(body)}\n\n`)
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
  const config = await readPersistedConfig(input.config ?? existing?.config)
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

async function handleRequest(request: IncomingMessage, response: ServerResponse): Promise<void> {
  if (request.method === 'OPTIONS') {
    response.writeHead(204, commonHeaders(request))
    response.end()
    return
  }
  if (request.url === '/health' && request.method === 'GET') {
    sendJson(request, response, 200, { ok: true, runtime: 'pi' })
    return
  }
  if (request.url !== '/v1/chat' || request.method !== 'POST') {
    sendJson(request, response, 404, { error: 'not found' })
    return
  }

  try {
    await handleChat(request, response, await readBody(request))
  } catch (error) {
    const detail = error instanceof Error ? error.message : String(error)
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
  console.log(`MBForge Pi agent listening on http://${host}:${port}`)
})
