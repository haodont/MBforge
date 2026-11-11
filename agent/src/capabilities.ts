import { readFile } from 'node:fs/promises'

import { Type } from 'typebox'
import { defineTool, type ToolDefinition } from '@earendil-works/pi-coding-agent'
import type { TSchema } from 'typebox'

import {
  citationGuidelines,
  harvestEvidence,
  rememberEvidence,
} from './citations.js'
import { capabilityRenderers } from './toolRender.js'
import { uiGuidelines } from './uiLinks.js'

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

export type CapabilityTool = ToolDefinition<TSchema>

export interface CapabilityToolset {
  tools: CapabilityTool[]
  mutatingNames: string[]
}

interface ImagePayload {
  base64: string
  mimeType: string
  metadata: Record<string, unknown>
}

interface CapabilityErrorBody {
  error: string
  detail: string | null
  errorCode: string | null
  validation: string[]
}

/** Pull Pydantic validation messages out of an MBForge error context. */
function validationMessages(context: unknown): string[] {
  if (typeof context !== 'object' || context === null) return []
  if (!('validation_errors' in context) || !Array.isArray(context.validation_errors)) {
    return []
  }
  const messages: string[] = []
  for (const item of context.validation_errors.slice(0, 3)) {
    if (typeof item !== 'object' || item === null) continue
    const loc =
      'loc' in item && Array.isArray(item.loc) ? item.loc.map(String).join('.') : ''
    const msg = 'msg' in item && typeof item.msg === 'string' ? item.msg : ''
    if (msg) messages.push(loc ? `${loc}: ${msg}` : msg)
  }
  return messages
}

/** Parse the server's structured error body; undefined means non-JSON output. */
function parseCapabilityError(body: string): CapabilityErrorBody | undefined {
  let value: unknown
  try {
    value = JSON.parse(body)
  } catch {
    return undefined
  }
  if (typeof value !== 'object' || value === null) return undefined
  if (!('error' in value) || typeof value.error !== 'string') return undefined
  return {
    error: value.error,
    detail: 'detail' in value && typeof value.detail === 'string' ? value.detail : null,
    errorCode:
      'error_code' in value && typeof value.error_code === 'string'
        ? value.error_code
        : null,
    validation: validationMessages('context' in value ? value.context : undefined),
  }
}

function capabilityFailure(name: string, status: number, body: string): Error {
  const parsed = parseCapabilityError(body)
  if (parsed === undefined) {
    return new Error(`capability ${name} failed (${status}): ${body.slice(0, 400)}`)
  }
  const parts = [
    parsed.errorCode ? `${parsed.errorCode}: ${parsed.error}` : parsed.error,
    parsed.detail,
    ...parsed.validation,
  ].filter((part): part is string => Boolean(part))
  return new Error(`capability ${name} failed (${status}): ${parts.join('; ')}`)
}

/** Detect a capability result that carries an inspectable image. */
function imagePayload(data: unknown): ImagePayload | undefined {
  if (typeof data !== 'object' || data === null) return undefined
  if (!('image_base64' in data) || typeof data.image_base64 !== 'string') {
    return undefined
  }
  const metadata: Record<string, unknown> = { ...data }
  delete metadata.image_base64
  const mimeType =
    'mime_type' in data && typeof data.mime_type === 'string'
      ? data.mime_type
      : 'image/png'
  return { base64: data.image_base64, mimeType, metadata }
}

/**
 * Run ids a capability result reports, so the caller can watch them to a
 * terminal status. `submit_patent_analysis` returns `run_ids`; the other
 * run-producing capabilities return one `run_id`.
 */
function runIdsFromData(data: unknown): string[] {
  if (typeof data !== 'object' || data === null) return []
  const ids: string[] = []
  if ('run_id' in data && typeof data.run_id === 'string' && data.run_id !== '') {
    ids.push(data.run_id)
  }
  if ('run_ids' in data && Array.isArray(data.run_ids)) {
    for (const id of data.run_ids) {
      if (typeof id === 'string' && id !== '') ids.push(id)
    }
  }
  return ids
}

/**
 * Prompt guidance for one capability: citation markers for evidence rows, workbench
 * link markers for results the user should see in the UI.
 */
function toolGuidelines(name: string): string[] | undefined {
  const guidelines = [
    ...(citationGuidelines(name) ?? []),
    ...(uiGuidelines(name) ?? []),
  ]
  return guidelines.length > 0 ? guidelines : undefined
}

// The manifest is a trivial local endpoint; a short timeout keeps CLI startup
// fast when the backend accepts connections but stalls.
const MANIFEST_TIMEOUT_MS = 2_000

export const backendBaseUrl = (): string =>
  process.env.MBFORGE_BACKEND_URL ??
  `http://${process.env.MBFORGE_BACKEND_HOST ?? '127.0.0.1'}:${process.env.MBFORGE_BACKEND_PORT ?? '18792'}`

/**
 * Read the capability token, or return nothing when it is not configured.
 *
 * Withholding the token is how a library stays unmutated: the request goes out
 * without the credential and the backend answers every mutating capability
 * with 403, so this is a downgrade path rather than an error.
 */
async function readToken(path: string): Promise<string | undefined> {
  try {
    const token = (await readFile(path, 'utf8')).trim()
    return token === '' ? undefined : token
  } catch {
    return undefined
  }
}

/** Load every capability; the caller decides which names are active. */
export async function loadCapabilityToolset(
  onRunEnqueued?: (runId: string) => void,
): Promise<CapabilityToolset> {
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

  const tools = manifest.capabilities.map((capability) =>
    defineTool({
      name: capability.name,
      label: capability.name,
      description: capability.description,
      promptGuidelines: toolGuidelines(capability.name),
      parameters: Type.Unsafe<Record<string, unknown>>(capability.input_schema),
      ...capabilityRenderers(capability.name),
      async execute(_toolCallId, params, signal) {
        const headers: Record<string, string> = {
          'content-type': 'application/json',
        }
        if (capability.mutating) {
          const token = await readToken(tokenPath)
          if (token !== undefined) headers['x-mbforge-token'] = token
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
          const detail = await result.text()
          throw capabilityFailure(capability.name, result.status, detail)
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
        for (const runId of runIdsFromData(payload.data)) {
          onRunEnqueued?.(runId)
        }
        const evidenceIndex = harvestEvidence(
          capability.name,
          params,
          payload.data,
        )
        for (const location of evidenceIndex) rememberEvidence(location)

        const image = imagePayload(payload.data)
        if (image) {
          return {
            content: [
              {
                type: 'text',
                text: JSON.stringify({
                  ...image.metadata,
                  image: 'attached as image content',
                }),
              },
              {
                type: 'image',
                data: image.base64,
                mimeType: image.mimeType,
              },
            ],
            details: { ...payload, data: image.metadata, evidenceIndex },
          }
        }

        const textPayload =
          payload.truncated || payload.next_offset != null
            ? {
                data: payload.data ?? null,
                truncated: Boolean(payload.truncated),
                next_offset: payload.next_offset ?? null,
              }
            : (payload.data ?? null)

        return {
          content: [{ type: 'text', text: JSON.stringify(textPayload) }],
          details: { ...payload, evidenceIndex },
        }
      },
    }),
  )

  return {
    tools,
    mutatingNames: manifest.capabilities
      .filter((capability) => capability.mutating)
      .map((capability) => capability.name),
  }
}
