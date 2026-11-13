import { readFile } from 'node:fs/promises'
import { setTimeout as sleep } from 'node:timers/promises'

import { Type } from 'typebox'
import {
  defineTool,
  type ToolDefinition,
} from '@earendil-works/pi-coding-agent'
import type { TSchema } from 'typebox'

import {
  citationGuidelines,
  harvestEvidence,
  rememberEvidence,
} from './citations.js'
import { backendAddress } from './backendControl.js'
import { errorMessage } from './text.js'
import { toolRenderers } from './toolRender.js'
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
  if (
    !('validation_errors' in context) ||
    !Array.isArray(context.validation_errors)
  ) {
    return []
  }
  const messages: string[] = []
  for (const item of context.validation_errors.slice(0, 3)) {
    if (typeof item !== 'object' || item === null) continue
    const loc =
      'loc' in item && Array.isArray(item.loc)
        ? item.loc.map(String).join('.')
        : ''
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
    detail:
      'detail' in value && typeof value.detail === 'string'
        ? value.detail
        : null,
    errorCode:
      'error_code' in value && typeof value.error_code === 'string'
        ? value.error_code
        : null,
    validation: validationMessages(
      'context' in value ? value.context : undefined,
    ),
  }
}

/** One actionable next step for a known failure, so the model recovers instead of retrying blindly. */
function recoveryHint(
  status: number,
  errorCode: string | null,
): string | undefined {
  switch (errorCode) {
    case 'capability_forbidden':
      return 'this write is gated by the capability token; report that it is blocked in this session instead of retrying'
    case 'not_found':
      return 'resolve the document or record first (resolve_document) and use an id from a tool result, not a guess'
    case 'validation_error':
      return 'fix the listed field errors and retry once'
    case 'model_not_available':
    case 'resource_not_available':
      return 'required model weights or resources are not ready; check get_worker_status before retrying'
    case 'conflict':
      return 'the record changed or a decision conflicts; re-read it before retrying'
    case 'path_traversal':
      return 'the path is outside the library; use a library-local path'
    default:
      break
  }
  if (status === 403) {
    return 'this call is not permitted in the current session; report it instead of retrying'
  }
  if (status === 404) {
    return 'the referenced item was not found; resolve it from a tool result instead of guessing'
  }
  if (status >= 500) {
    return 'the backend failed unexpectedly; report it and check the backend log rather than retrying in a loop'
  }
  return undefined
}

function capabilityFailure(name: string, status: number, body: string): Error {
  const parsed = parseCapabilityError(body)
  const hint = recoveryHint(status, parsed?.errorCode ?? null)
  const suffix = hint ? `; next: ${hint}` : ''
  if (parsed === undefined) {
    return new Error(
      `capability ${name} failed (${status}): ${body.slice(0, 400)}${suffix}`,
    )
  }
  const parts = [
    parsed.errorCode ? `${parsed.errorCode}: ${parsed.error}` : parsed.error,
    parsed.detail,
    ...parsed.validation,
  ].filter((part): part is string => Boolean(part))
  return new Error(
    `capability ${name} failed (${status}): ${parts.join('; ')}${suffix}`,
  )
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
  if (
    'run_id' in data &&
    typeof data.run_id === 'string' &&
    data.run_id !== ''
  ) {
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

/** Backend API base URL; the single resolver lives in backendControl. */
export const backendBaseUrl = (): string => backendAddress().baseUrl

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
  const tokenPath =
    process.env.MBFORGE_CAPABILITY_TOKEN_FILE ?? manifest.token_path

  const tools = manifest.capabilities.map((capability) =>
    defineTool({
      name: capability.name,
      label: capability.name,
      description: capability.description,
      promptGuidelines: toolGuidelines(capability.name),
      parameters: Type.Unsafe<Record<string, unknown>>(capability.input_schema),
      ...toolRenderers(capability.name, capability.mutating),
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

// Bound worst-case startup: a few short attempts tolerate a backend that is
// still coming up, then degrade to zero tools so pi opens promptly.
const MANIFEST_ATTEMPTS = 3
const MANIFEST_RETRY_DELAY_MS = 400

async function loadToolsetWithRetry(
  loadToolset: typeof loadCapabilityToolset,
  onRunEnqueued?: (runId: string) => void,
): Promise<CapabilityToolset> {
  let lastError: unknown
  for (let attempt = 1; attempt <= MANIFEST_ATTEMPTS; attempt += 1) {
    try {
      return await loadToolset(onRunEnqueued)
    } catch (error) {
      lastError = error
      if (attempt < MANIFEST_ATTEMPTS) {
        await sleep(MANIFEST_RETRY_DELAY_MS)
      }
    }
  }
  throw lastError instanceof Error ? lastError : new Error(String(lastError))
}

export type CapabilityReloadResult =
  { ok: true; count: number } | { ok: false; error: string }

export interface CapabilityToolsetManager {
  readonly tools: CapabilityTool[]
  readonly mutatingNames: string[]
  readonly loadError: string | undefined
  /** Initial load; failure degrades to zero tools and records the reason. */
  load(): Promise<void>
  /** Refresh the manifest; on failure the previous toolset stays active. */
  reload(): Promise<CapabilityReloadResult>
}

/**
 * The session's capability toolset, reloadable while pi runs.
 *
 * The backend lifecycle is dynamic (`backend_control` can start or restart it
 * mid-session), so the manifest cannot be a startup-only snapshot. `reload`
 * re-fetches and re-registers every capability — pi replaces a tool registered
 * under the same name — and the caller re-applies the active set from `tools`,
 * which drops capabilities the new manifest no longer lists. A failed reload
 * keeps the previous toolset: a running session must not lose its tools
 * because one refresh could not reach the backend.
 */
export function createCapabilityToolsetManager(
  registerTool: (tool: CapabilityTool) => void,
  onRunEnqueued?: (runId: string) => void,
  loadToolset: typeof loadCapabilityToolset = loadCapabilityToolset,
): CapabilityToolsetManager {
  let tools: CapabilityTool[] = []
  let mutatingNames: string[] = []
  let loadError: string | undefined

  async function fetchAndRegister(): Promise<number> {
    const toolset = await loadToolsetWithRetry(loadToolset, onRunEnqueued)
    for (const tool of toolset.tools) registerTool(tool)
    tools = toolset.tools
    mutatingNames = toolset.mutatingNames
    loadError = undefined
    return tools.length
  }

  return {
    get tools(): CapabilityTool[] {
      return tools
    },
    get mutatingNames(): string[] {
      return mutatingNames
    },
    get loadError(): string | undefined {
      return loadError
    },
    /** Initial load; failure degrades to zero tools and records the reason. */
    async load(): Promise<void> {
      try {
        await fetchAndRegister()
      } catch (error) {
        loadError = errorMessage(error)
      }
    },
    /** Refresh the manifest; on failure the previous toolset stays active. */
    async reload(): Promise<CapabilityReloadResult> {
      try {
        return { ok: true, count: await fetchAndRegister() }
      } catch (error) {
        const message = errorMessage(error)
        if (tools.length === 0) loadError = message
        return { ok: false, error: message }
      }
    },
  }
}
