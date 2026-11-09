/** Research turns use Python-bound credentials and durable Pi conversation files. */
import { existsSync } from 'node:fs'
import type { IncomingMessage, ServerResponse } from 'node:http'
import { SessionManager, defineTool } from '@earendil-works/pi-coding-agent'
import { Type } from '@earendil-works/pi-ai'
import { startSse, writeSse, sendJson } from './http.js'
import { asRecord, loadPersistedLlmConfig, readConfig, sanitizeError, stringValue, type AgentLlmConfig } from './llm.js'
import { createSessionForSpec } from './session.js'
import { postTool, searchLibraryParameters } from './tool.js'
import { researchPrompt } from './prompts.js'
import { loadSkillTool, researchSkills } from './skills.js'
import { createScientificSearchTools } from './scientific.js'
import { createWebTools, loadWebConfig } from './web.js'

interface TaskReference { task_id: string; run_id: string; doc_id: string }
interface ArtifactReference { doc_id: string; run_id: string; revision: number }
interface RuntimeSpec {
  session_id: string
  session_file: string
  message: string
  context: { document_ids: string[]; molecule_refs: Array<{ mol_id: string; name: string }>; task_refs: TaskReference[]; allow_patent_analysis: boolean }
  history: Array<{ role: 'user' | 'assistant'; content: string; status: string }>
}

const activeSessions = new Map<string, string>()

export function handleResearchStatus(request: IncomingMessage, response: ServerResponse, body: unknown): void {
  const input = asRecord(body)
  if (Object.keys(input).some(key => key !== 'session_id') || typeof input.session_id !== 'string' || !/^[a-z0-9_-]{1,128}$/i.test(input.session_id)) {
    sendJson(request, response, 422, { error: 'A research session identifier is required' })
    return
  }
  sendJson(request, response, 200, { active: [...activeSessions.values()].includes(input.session_id) })
}

export async function handleResearchChat(request: IncomingMessage, response: ServerResponse, body: unknown): Promise<void> {
  const input = asRecord(body)
  if (Object.keys(input).some(key => key !== 'credential') || typeof input.credential !== 'string' || input.credential.length < 20 || input.credential.length > 128) {
    sendJson(request, response, 422, { error: 'A research turn credential is required' })
    return
  }
  const credential = input.credential
  // The backend supplies the path after resolving its credential. No caller or
  // model can choose a sidecar file path or a different library.
  const spec = await scopedPostTool<RuntimeSpec>(credential, '/api/v1/research/runtime/spec', { credential })
  if (activeSessions.has(spec.session_file)) {
    sendJson(request, response, 409, { error: 'This research conversation is already running' })
    return
  }
  activeSessions.set(spec.session_file, spec.session_id)
  let config: AgentLlmConfig | undefined
  let closed = false
  let text = ''
  let budgetExceeded = false
  let turns = 0
  let session: Awaited<ReturnType<typeof createSessionForSpec>> | undefined
  const emit = (name: string, payload: unknown) => { if (!closed) writeSse(response, name, payload) }
  const tools = [
    loadSkillTool,
    defineTool({ name: 'search_library', label: 'Search library text', description: 'Search extracted source text across the bound library. Returns document/page/evidence IDs, bounded snippets and pagination; no match does not prove absence.', parameters: searchLibraryParameters,
      async execute(_id, params, signal) { return result(await scopedPostTool(credential, '/api/v1/research/runtime/search-library', { credential, query: params }, signal)) } }),
    defineTool({ name: 'library_stats', label: 'Library overview', description: 'Read counts in this research conversation’s bound library.', parameters: Type.Object({}),
      async execute(_id, _params, signal) { return result(await scopedPostTool(credential, '/api/v1/research/runtime/library-stats', { credential }, signal)) } }),
    defineTool({ name: 'molecule_search', label: 'Molecule search', description: 'Find stored molecules in the bound library. Results are source records, not validated design recommendations.',
      parameters: Type.Object({ query: Type.String({ minLength: 1, maxLength: 512 }), mode: Type.Optional(Type.Union([Type.Literal('auto'), Type.Literal('text'), Type.Literal('substructure'), Type.Literal('similarity')])) }),
      async execute(_id, params, signal) { return result(await scopedPostTool(credential, '/api/v1/research/runtime/molecule-search', { credential, query: params }, signal)) } }),
    defineTool({ name: 'query_documents', label: 'Find documents', description: 'Find document identifiers and preparation states in the bound library.',
      parameters: Type.Object({ name: Type.Optional(Type.String({ maxLength: 256 })), status: Type.Optional(Type.String({ maxLength: 64 })) }),
      async execute(_id, params, signal) { return result(await scopedPostTool(credential, '/api/v1/research/runtime/query-documents', { credential, query: params }, signal)) } }),
    defineTool({ name: 'query_evidence', label: 'Read source evidence', description: 'Read source text and identifiers from a registered document in the bound library.',
      parameters: Type.Object({ doc_id: Type.String({ maxLength: 128 }), page: Type.Optional(Type.Integer({ minimum: 1 })), text: Type.Optional(Type.String({ maxLength: 512 })) }),
      async execute(_id, params, signal) { return result(await scopedPostTool(credential, '/api/v1/research/runtime/query-evidence', { credential, query: params }, signal)) } }),
    defineTool({ name: 'recognize_molecules', label: 'Recognize drawn molecules', description: 'Run the local MolDet + MolParser recognizers over one page of a bound document (optionally one PDF-point region). Returns SMILES/E-SMILES, PDF-point bbox and OCR-read printed labels, read-only. Use it for structure or SMILES questions and to tie a printed designation to its drawing; never author a SMILES yourself, and report an empty result as "not detected".',
      parameters: Type.Object({
        doc_id: Type.String({ minLength: 1, maxLength: 128 }),
        page: Type.Integer({ minimum: 1 }),
        region: Type.Optional(Type.Array(Type.Number(), { minItems: 4, maxItems: 4 })),
        max_molecules: Type.Optional(Type.Integer({ minimum: 1, maximum: 20 })),
      }),
      async execute(_id, params, signal) { return result(await scopedPostTool(credential, '/api/v1/research/runtime/recognize-molecules', { credential, ...params }, signal)) } }),
    defineTool({ name: 'query_activities', label: 'Read activities', description: 'Read accepted activity records, optionally library-wide. Preserve comparator, unit, species and assay distinctions; each row says why it has no structure.',
      parameters: Type.Object({
        doc_id: Type.Optional(Type.String({ maxLength: 128 })),
        target: Type.Optional(Type.String({ maxLength: 256 })),
        metric: Type.Optional(Type.String({ maxLength: 64 })),
        min_value: Type.Optional(Type.Number()),
        max_value: Type.Optional(Type.Number()),
        limit: Type.Optional(Type.Integer({ minimum: 1, maximum: 200 })),
      }),
      async execute(_id, params, signal) { return result(await scopedPostTool(credential, '/api/v1/research/runtime/query-activities', { credential, query: params }, signal)) } }),
    defineTool({ name: 'activity_stats', label: 'Activity coverage', description: 'Read how many printed readings exist and how many reached a structure, with the reason each unattributed reading has none. Use it before claiming there is no activity data.',
      parameters: Type.Object({ doc_id: Type.Optional(Type.String({ maxLength: 128 })) }),
      async execute(_id, params, signal) { return result(await scopedPostTool(credential, '/api/v1/research/runtime/activity-stats', { credential, doc_id: params.doc_id ?? '' }, signal)) } }),
    defineTool({ name: 'query_tasks', label: 'Read task status', description: 'Read current queue status; reading does not start or cancel tasks.',
      parameters: Type.Object({ run_id: Type.Optional(Type.String({ maxLength: 128 })) }),
      async execute(_id, params, signal) { return result(await scopedPostTool(credential, '/api/v1/research/runtime/query-tasks', { credential, ...params }, signal)) } }),
    defineTool({ name: 'propose_review', label: 'Propose a review item',
      description: 'Record a correction you found in an existing target a human has not reviewed yet (evidence row, measurement, molecule, entry or designation). The proposal enters the review center for a human to confirm or reject; it never changes data itself, and a target a human already decided is refused. Cite the evidence ids you actually read, and never invent a value you did not see.',
      parameters: Type.Object({
        doc_id: Type.Optional(Type.String({ maxLength: 128 })),
        target_kind: Type.Union([Type.Literal('evidence'), Type.Literal('measurement'), Type.Literal('molecule'), Type.Literal('entry'), Type.Literal('designation')]),
        target_id: Type.String({ minLength: 1, maxLength: 200 }),
        field: Type.Optional(Type.String({ maxLength: 80 })),
        before: Type.Optional(Type.String({ maxLength: 4000 })),
        after: Type.String({ minLength: 1, maxLength: 4000 }),
        rationale: Type.Optional(Type.String({ maxLength: 2000 })),
        evidence_ids: Type.Optional(Type.Array(Type.String({ maxLength: 128 }), { maxItems: 32 })),
      }),
      async execute(_id, params, signal) {
        const payload = await scopedPostTool<{ items: Array<Record<string, unknown>> }>(credential, '/api/v1/research/runtime/propose-review', { credential, items: [params] }, signal)
        const refs = (Array.isArray(payload.items) ? payload.items : [])
          .filter(item => item && item.action !== 'refused')
          .map(item => {
            const record = asRecord(item.payload)
            const proposal = asRecord(record.proposal)
            return {
              item_id: stringValue(item.item_id, '', 128),
              kind: 'ai_review',
              doc_id: stringValue(proposal.doc_id, '', 128),
              target_kind: stringValue(proposal.target_kind, '', 40),
              target_id: stringValue(proposal.target_id, '', 200),
              field: stringValue(proposal.field, '', 80),
              before_actual: stringValue(record.before_actual, '', 4000),
              after: stringValue(proposal.after, '', 4000),
              rationale: stringValue(proposal.rationale, '', 2000),
              status: stringValue(item.status, 'pending', 20),
            }
          })
          .filter(ref => ref.item_id !== '')
        if (refs.length > 0) emit('review', { items: refs })
        return result(payload)
      } }),
    defineTool({ name: 'start_patent_analysis', label: 'Analyze selected patents', description: 'Queue Patent analysis only for explicitly authorized selected document identifiers. Repeating the same request reuses the existing task.',
      parameters: Type.Object({ doc_ids: Type.Array(Type.String({ maxLength: 128 }), { minItems: 1, maxItems: 8 }) }),
      async execute(_id, params, signal) {
        const payload = await scopedPostTool<{ references: TaskReference[] }>(credential, '/api/v1/research/runtime/start-patent-analysis', { credential, ...params }, signal)
        for (const reference of payload.references) emit('task', { reference })
        return result(payload)
      } }),
    defineTool({ name: 'get_patent_facts', label: 'Read analysis result', description: 'Read the current published Patent fact summary and its revision. Pending candidates are not accepted facts.',
      parameters: Type.Object({ doc_id: Type.String({ maxLength: 128 }) }),
      async execute(_id, params, signal) {
        const payload = await scopedPostTool<{ reference: ArtifactReference | null }>(credential, '/api/v1/research/runtime/patent-facts', { credential, ...params }, signal)
        if (payload.reference) emit('artifact', { reference: payload.reference })
        return result(payload)
      } }),
  ]
  try {
    config = readConfig({}, await loadPersistedLlmConfig())
    const webConfig = await loadWebConfig()
    const web = await createWebTools(webConfig)
    const scientificTools = webConfig.enabled ? createScientificSearchTools() : []
    web.reset(spec.message)
    const restoring = existsSync(spec.session_file)
    session = await createSessionForSpec({ ...config, requestTimeoutMs: Math.min(config.requestTimeoutMs, 120000) }, {
      systemPrompt: researchPrompt(web.toolNames.length > 0),
      toolNames: [...tools.map(tool => tool.name), ...scientificTools.map(tool => tool.name), ...web.toolNames],
      customTools: [...tools, ...scientificTools], skills: researchSkills,
      extensions: web.extensions,
      sessionManager: SessionManager.open(spec.session_file),
    })
    startSse(request, response)
    const onClose = () => { closed = true; if (session?.isStreaming) void session.abort() }
    response.once('close', onClose)
    const deadline = setTimeout(() => { budgetExceeded = true; void session?.abort() }, 600000)
    deadline.unref()
    const unsubscribe = session.subscribe(event => {
      // Pi persists message_end after notifying listeners; redact before that write.
      if (event.type === 'message_end' && event.message.role === 'assistant' && event.message.errorMessage) {
        event.message.errorMessage = sanitizeError(sanitizeError(event.message.errorMessage, config?.apiKey ?? ''), credential)
      }
      if (closed) return
      if (event.type === 'turn_start' && ++turns > 24) { budgetExceeded = true; void session?.abort() }
      if (event.type === 'message_update' && event.assistantMessageEvent.type === 'text_delta') {
        const delta = event.assistantMessageEvent.delta
        if (text.length + delta.length > 60000) { budgetExceeded = true; void session?.abort(); return }
        text += delta
        emit('delta', { text: delta })
      } else if (event.type === 'tool_execution_start') emit('tool', { name: event.toolName, status: 'start' })
      else if (event.type === 'tool_execution_end') emit('tool', { name: event.toolName, status: event.isError ? 'error' : 'done' })
    })
    try {
      await session.prompt(JSON.stringify({ question: spec.message, context: spec.context,
        ...(restoring ? {} : { history_excerpt: spec.history.filter(message => message.status === 'complete').slice(-12).map(({ role, content }) => ({ role, content: content.slice(0, 2000) })) }),
      }), { expandPromptTemplates: false, source: 'rpc' })
      const error = session.agent.state.errorMessage
      if (budgetExceeded) emit('error', { message: 'The research reply reached its time, turn or response limit. Background tasks continue independently.' })
      else if (error) emit('error', { message: sanitizeError(error, config.apiKey).slice(0, 500) })
      else emit('done', { text, status: 'complete' })
    } finally {
      clearTimeout(deadline)
      unsubscribe()
      response.removeListener('close', onClose)
    }
  } catch (error) {
    if (response.headersSent) emit('error', { message: sanitizeError(error, config?.apiKey ?? '').slice(0, 500) })
    else sendJson(request, response, 503, { error: sanitizeError(error, config?.apiKey ?? '').slice(0, 500) })
  } finally {
    session?.dispose()
    activeSessions.delete(spec.session_file)
    if (response.headersSent && !response.writableEnded) response.end()
  }
}

function result(payload: unknown) {
  return { content: [{ type: 'text' as const, text: JSON.stringify(payload) }], details: {} }
}

async function scopedPostTool<T>(credential: string, path: string, body: unknown, signal?: AbortSignal): Promise<T> {
  try { return await postTool<T>(path, body, signal) }
  catch (error) { throw new Error(sanitizeError(error, credential)) }
}
