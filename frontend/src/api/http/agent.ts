export interface AgentLlmConfig {
  provider: string
  model: string
  api_key: string
  base_url: string
  max_tokens?: number
  request_timeout?: number
}

export interface AgentChatEvent {
  type: 'delta' | 'tool' | 'done' | 'error'
  data: Record<string, unknown>
}

export interface AgentChatRequest {
  message: string
  session_id?: string
  config: AgentLlmConfig
}

function agentUrl(path: string): string {
  const override = String(import.meta.env.VITE_AGENT_URL ?? '').replace(/\/$/, '')
  if (override) return `${override}${path}`
  // Dev: reach the LLM agent through Vite's same-origin proxy
  // (frontend/scripts/dev-all.mjs, vite.config.ts `/agent-api`).
  if (import.meta.env.DEV) return `/agent-api${path}`
  // Production: default to the standalone agent origin.
  return `http://127.0.0.1:18800${path}`
}

function parseEvent(frame: string): AgentChatEvent | null {
  let type = 'message'
  const data: string[] = []
  for (const line of frame.split(/\r?\n/)) {
    if (line.startsWith('event:')) type = line.slice(6).trim()
    if (line.startsWith('data:')) data.push(line.slice(5).trimStart())
  }
  if (data.length === 0) return null
  try {
    return { type: type as AgentChatEvent['type'], data: JSON.parse(data.join('\n')) as Record<string, unknown> }
  } catch {
    return null
  }
}

export async function streamAgentChat(
  input: AgentChatRequest,
  onEvent: (event: AgentChatEvent) => void,
  signal?: AbortSignal,
): Promise<{ sessionId?: string }> {
  const response = await fetch(agentUrl('/v1/chat'), {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(input),
    signal,
  })

  if (!response.ok) {
    const body = await response.text()
    throw new Error(`Agent request failed (${response.status}): ${body.slice(0, 400)}`)
  }

  const reader = response.body?.getReader()
  if (!reader) throw new Error('Agent returned no stream')

  const decoder = new TextDecoder()
  let buffer = ''
  let sessionId: string | undefined
  try {
    for (;;) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      let boundary = buffer.indexOf('\n\n')
      while (boundary >= 0) {
        const event = parseEvent(buffer.slice(0, boundary))
        buffer = buffer.slice(boundary + 2)
        if (event) {
          onEvent(event)
          if (event.type === 'done' && typeof event.data.session_id === 'string') {
            sessionId = event.data.session_id
          }
        }
        boundary = buffer.indexOf('\n\n')
      }
    }
    const trailing = parseEvent(buffer)
    if (trailing) onEvent(trailing)
  } finally {
    reader.releaseLock()
  }
  return { sessionId }
}
