/** HTTP plumbing shared by the sidecar's chat and Patent-analysis entries. */

import type { IncomingMessage, ServerResponse } from 'node:http'

/** Request-body cap for every sidecar entry (512 KB). */
export const MAX_BODY_BYTES = 512 * 1024

export function corsOrigin(request: IncomingMessage): string {
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

export function commonHeaders(request: IncomingMessage): Record<string, string> {
  return {
    'access-control-allow-origin': corsOrigin(request),
    'access-control-allow-headers': 'content-type',
    'access-control-allow-methods': 'GET,POST,OPTIONS',
    vary: 'origin',
  }
}

export function sendJson(
  request: IncomingMessage,
  response: ServerResponse,
  status: number,
  body: unknown,
): void {
  response.writeHead(status, {
    ...commonHeaders(request),
    'content-type': 'application/json; charset=utf-8',
  })
  response.end(JSON.stringify(body))
}

export function startSse(request: IncomingMessage, response: ServerResponse): void {
  response.writeHead(200, {
    ...commonHeaders(request),
    'content-type': 'text/event-stream; charset=utf-8',
    'cache-control': 'no-cache, no-transform',
    connection: 'keep-alive',
  })
}

export function writeSse(response: ServerResponse, event: string, body: unknown): void {
  if (response.writableEnded) return
  response.write('event: ' + event + '\ndata: ' + JSON.stringify(body) + '\n\n')
}

export async function readBody(request: IncomingMessage): Promise<unknown> {
  const chunks: Buffer[] = []
  let length = 0
  for await (const chunk of request) {
    const buffer = Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk)
    length += buffer.length
    if (length > MAX_BODY_BYTES) throw new Error('request body is too large')
    chunks.push(buffer)
  }
  return JSON.parse(Buffer.concat(chunks).toString('utf8'))
}
