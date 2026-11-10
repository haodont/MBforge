import { readFile } from 'node:fs/promises'

import { Type } from 'typebox'
import { defineTool, type ToolDefinition } from '@earendil-works/pi-coding-agent'
import type { TSchema } from 'typebox'

interface CapabilityInfo {
  name: string
  description: string
  mutating: boolean
  input_schema: Record<string, unknown>
}

interface CapabilityManifest {
  success: boolean
  capabilities: CapabilityInfo[]
  token_path: string
}

export type AgentMode = 'readonly' | 'edit'
export type CapabilityTool = ToolDefinition<TSchema>

// The manifest is a trivial local endpoint; a short timeout keeps CLI startup
// fast when the backend accepts connections but stalls.
const MANIFEST_TIMEOUT_MS = 2_000

export const backendBaseUrl = (): string =>
  process.env.MBFORGE_BACKEND_URL ??
  `http://${process.env.MBFORGE_BACKEND_HOST ?? '127.0.0.1'}:${process.env.MBFORGE_BACKEND_PORT ?? '18792'}`

async function readToken(path: string): Promise<string> {
  return (await readFile(path, 'utf8')).trim()
}

export async function loadCapabilityTools(
  mode: AgentMode,
): Promise<CapabilityTool[]> {
  const response = await fetch(`${backendBaseUrl()}/api/v1/capabilities`, {
    signal: AbortSignal.timeout(MANIFEST_TIMEOUT_MS),
  })
  if (!response.ok) {
    throw new Error(`capability manifest failed (${response.status})`)
  }
  const manifest = (await response.json()) as CapabilityManifest
  if (!manifest.success || !Array.isArray(manifest.capabilities)) {
    throw new Error('invalid capability manifest')
  }
  const tokenPath = process.env.MBFORGE_CAPABILITY_TOKEN_FILE ?? manifest.token_path

  return manifest.capabilities
    .filter((capability) => mode === 'edit' || !capability.mutating)
    .map((capability) =>
      defineTool({
        name: capability.name,
        label: capability.name,
        description: capability.description,
        parameters: Type.Unsafe<Record<string, unknown>>(capability.input_schema),
        async execute(_toolCallId, params, signal) {
          const headers: Record<string, string> = {
            'content-type': 'application/json',
          }
          if (mode === 'edit' && capability.mutating) {
            headers['x-mbforge-token'] = await readToken(tokenPath)
          }
          const result = await fetch(
            `${backendBaseUrl()}/api/v1/capabilities/${capability.name}`,
            {
              method: 'POST',
              headers,
              body: JSON.stringify(params),
              signal,
            },
          )
          if (!result.ok) {
            const detail = (await result.text()).slice(0, 400)
            throw new Error(`capability ${capability.name} failed (${result.status}): ${detail}`)
          }
          const payload = (await result.json()) as {
            success?: boolean
            data?: unknown
            truncated?: boolean
            next_offset?: number | null
          }
          if (!payload.success) {
            throw new Error(`capability ${capability.name} returned an error`)
          }
          const textPayload =
            payload.truncated || payload.next_offset !== null
              ? {
                  data: payload.data ?? null,
                  truncated: Boolean(payload.truncated),
                  next_offset: payload.next_offset ?? null,
                }
              : (payload.data ?? null)
          return {
            content: [{ type: 'text', text: JSON.stringify(textPayload) }],
            details: payload,
          }
        },
      }),
    )
}
