/**
 * Cross-session research work ledger.
 *
 * The agent's library context lives in SQL (the briefing reads it) and its
 * durable lessons live in memory, but neither records *the research work in
 * progress*: the active objective, design hypotheses, pending follow-ups and
 * decisions that span sessions and days. A pi session branch only survives a
 * resume of that same session; a fresh session starts blind.
 *
 * This ledger is the global, process-independent home for that work state. It
 * is agent-local (not library evidence, not visible to the workbench), bounded,
 * and injected into every new session's prompt so the agent resumes grounded.
 * The `goal` tool mirrors its active objective here; `work_state` reads and
 * updates the threads.
 */

import { randomUUID } from 'node:crypto'
import { join, resolve } from 'node:path'

import {
  defineTool,
  getAgentDir,
  type ExtensionAPI,
} from '@earendil-works/pi-coding-agent'
import { Type } from 'typebox'

import { atomicWrite, createSerializer, readJsonFile } from './localStore.js'
import { toolRenderers } from './toolRender.js'

const WORK_STATE_FILE_NAME = 'WORK_STATE.json'
const MAX_THREADS = 50
const MAX_TITLE_CHARS = 160
const MAX_DETAIL_CHARS = 2_000
const MAX_REFS = 16
const MAX_REF_CHARS = 200
const PROMPT_THREAD_LIMIT = 12
const PROMPT_DETAIL_CHARS = 200

export const WORK_THREAD_KINDS = [
  'hypothesis',
  'follow_up',
  'decision',
  'note',
] as const
export type WorkThreadKind = (typeof WORK_THREAD_KINDS)[number]

export type WorkThreadStatus = 'open' | 'done'

export const WORK_LINK_KINDS = ['run', 'review', 'document'] as const
export type WorkLinkKind = (typeof WORK_LINK_KINDS)[number]

/** A server object a follow_up waits on; ``sub`` is the review kind for review links. */
export interface WorkLink {
  kind: WorkLinkKind
  id: string
  sub?: string
}

export interface WorkThread {
  id: string
  kind: WorkThreadKind
  title: string
  detail: string
  status: WorkThreadStatus
  refs: string[]
  link?: WorkLink
  last_checked?: string
  check_note?: string
  created_at: string
  updated_at: string
}

export interface ActiveGoal {
  id: string
  title: string
  objective: string
}

export interface WorkState {
  version: 1
  active_goal: ActiveGoal | null
  threads: WorkThread[]
  updated_at: string
}

export const WORK_STATE_TOOL_NAME = 'work_state'
export const WORK_STATE_TOOL_NAMES = [WORK_STATE_TOOL_NAME] as const

export const WORK_STATE_ACTIONS = ['list', 'add', 'update', 'close', 'check'] as const
export type WorkStateAction = (typeof WORK_STATE_ACTIONS)[number]

/** Local ledger path; override with MBFORGE_WORK_STATE_FILE for tests. */
export function workStateFilePath(): string {
  const override = process.env.MBFORGE_WORK_STATE_FILE?.trim()
  return override ? resolve(override) : join(getAgentDir(), WORK_STATE_FILE_NAME)
}

function emptyState(): WorkState {
  return { version: 1, active_goal: null, threads: [], updated_at: '' }
}

function cleanText(value: string, field: string, max: number): string {
  const text = value.replace(/\r\n?/g, '\n').trim()
  if (!text) throw new Error(`${field} must not be empty`)
  if (text.length > max) throw new Error(`${field} must be at most ${max} characters`)
  if (/[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f]/.test(text)) {
    throw new Error(`${field} contains control characters`)
  }
  return text
}

function normalizeKind(value: string): WorkThreadKind {
  if ((WORK_THREAD_KINDS as readonly string[]).includes(value)) {
    return value as WorkThreadKind
  }
  throw new Error(`kind must be one of: ${WORK_THREAD_KINDS.join(', ')}`)
}

function normalizeRefs(refs: string[] | undefined): string[] {
  return (refs ?? [])
    .map((ref) => cleanText(ref, 'ref', MAX_REF_CHARS))
    .filter((ref, index, all) => all.indexOf(ref) === index)
    .slice(0, MAX_REFS)
}

function normalizeLink(link: WorkLink | undefined): WorkLink | undefined {
  if (link === undefined) return undefined
  if (!(WORK_LINK_KINDS as readonly string[]).includes(link.kind)) {
    throw new Error(`link kind must be one of: ${WORK_LINK_KINDS.join(', ')}`)
  }
  const id = cleanText(link.id, 'link id', MAX_REF_CHARS)
  const sub = link.sub ? cleanText(link.sub, 'link sub', MAX_REF_CHARS) : undefined
  return sub ? { kind: link.kind, id, sub } : { kind: link.kind, id }
}

function isThread(value: unknown): value is WorkThread {
  if (typeof value !== 'object' || value === null) return false
  const row = value as Partial<WorkThread>
  return (
    typeof row.id === 'string' &&
    typeof row.title === 'string' &&
    typeof row.kind === 'string' &&
    typeof row.status === 'string'
  )
}

async function readState(): Promise<WorkState> {
  const parsed = await readJsonFile(workStateFilePath())
  if (parsed === undefined) return emptyState()
  if (typeof parsed !== 'object' || parsed === null) {
    throw new Error(`Work state has an invalid shape: ${workStateFilePath()}`)
  }
  const record = parsed as Partial<WorkState>
  const threads = Array.isArray(record.threads) ? record.threads.filter(isThread) : []
  const goal = record.active_goal
  const active_goal =
    goal && typeof goal.id === 'string' && typeof goal.title === 'string'
      ? { id: goal.id, title: goal.title, objective: String(goal.objective ?? '') }
      : null
  return {
    version: 1,
    active_goal,
    threads,
    updated_at: typeof record.updated_at === 'string' ? record.updated_at : '',
  }
}

const serialize = createSerializer()

async function writeState(state: WorkState): Promise<void> {
  state.updated_at = new Date().toISOString()
  await atomicWrite(workStateFilePath(), `${JSON.stringify(state, null, 2)}\n`)
}

export interface WorkThreadInput {
  kind: WorkThreadKind
  title: string
  detail?: string
  refs?: string[]
  link?: WorkLink
}

/** Add one open work thread; newest first, bounded. */
export async function addWorkThread(input: WorkThreadInput): Promise<WorkThread> {
  const kind = normalizeKind(input.kind)
  const title = cleanText(input.title, 'title', MAX_TITLE_CHARS)
  const detail = input.detail ? cleanText(input.detail, 'detail', MAX_DETAIL_CHARS) : ''
  const refs = normalizeRefs(input.refs)
  const link = normalizeLink(input.link)
  return serialize(async () => {
    const state = await readState()
    const now = new Date().toISOString()
    const thread: WorkThread = {
      id: `wt-${randomUUID().slice(0, 8)}`,
      kind,
      title,
      detail,
      status: 'open',
      refs,
      ...(link ? { link } : {}),
      created_at: now,
      updated_at: now,
    }
    state.threads = [thread, ...state.threads].slice(0, MAX_THREADS)
    await writeState(state)
    return thread
  })
}

export interface WorkThreadUpdate {
  title?: string
  detail?: string
  status?: WorkThreadStatus
  refs?: string[]
  link?: WorkLink
  last_checked?: string
  check_note?: string
}

/** Update one thread's fields; returns the updated thread. */
export async function updateWorkThread(
  id: string,
  update: WorkThreadUpdate,
): Promise<WorkThread> {
  return serialize(async () => {
    const state = await readState()
    const thread = state.threads.find((item) => item.id === id)
    if (!thread) throw new Error(`Work thread not found: ${id}`)
    if (update.title !== undefined) thread.title = cleanText(update.title, 'title', MAX_TITLE_CHARS)
    if (update.detail !== undefined) thread.detail = cleanText(update.detail, 'detail', MAX_DETAIL_CHARS)
    if (update.refs !== undefined) thread.refs = normalizeRefs(update.refs)
    if (update.link !== undefined) thread.link = normalizeLink(update.link)
    if (update.last_checked !== undefined) thread.last_checked = update.last_checked
    if (update.check_note !== undefined) thread.check_note = update.check_note
    if (update.status !== undefined) {
      if (update.status !== 'open' && update.status !== 'done') {
        throw new Error('status must be open or done')
      }
      thread.status = update.status
    }
    thread.updated_at = new Date().toISOString()
    await writeState(state)
    return thread
  })
}

/** Mark one thread done. */
export async function closeWorkThread(id: string): Promise<WorkThread> {
  return updateWorkThread(id, { status: 'done' })
}

/** Mirror the active research goal (or clear it) into the durable ledger. */
export async function setActiveWorkGoal(goal: ActiveGoal | null): Promise<void> {
  await serialize(async () => {
    const state = await readState()
    state.active_goal = goal
    await writeState(state)
  })
}

/** Read the whole ledger (used by the tool and the prompt). */
export async function readWorkState(): Promise<WorkState> {
  return readState()
}

function clip(value: string, max: number): string {
  const single = value.replace(/\s+/g, ' ').trim()
  return single.length > max ? `${single.slice(0, max - 1)}…` : single
}

/**
 * Compact prompt section for a new session. Empty when nothing is recorded, so
 * a fresh library adds no noise. This is context, not evidence or instructions.
 */
export async function workStateSystemPrompt(): Promise<string> {
  const state = await readState()
  const open = state.threads.filter((thread) => thread.status === 'open')
  if (!state.active_goal && open.length === 0) return ''
  const lines: string[] = [
    '## Research work state',
    'Durable cross-session work ledger (agent-local context, not library evidence). Resume from it and keep it current with work_state.',
  ]
  if (state.active_goal) {
    lines.push(
      `Active goal: ${state.active_goal.title} — ${clip(state.active_goal.objective, PROMPT_DETAIL_CHARS)}`,
    )
  }
  if (open.length > 0) {
    lines.push('Open threads:')
    for (const thread of open.slice(0, PROMPT_THREAD_LIMIT)) {
      const detail = thread.detail ? `: ${clip(thread.detail, PROMPT_DETAIL_CHARS)}` : ''
      lines.push(`- [${thread.kind}] ${thread.title}${detail}`)
    }
    if (open.length > PROMPT_THREAD_LIMIT) {
      lines.push(`- … ${open.length - PROMPT_THREAD_LIMIT} more (use work_state action=list)`)
    }
  }
  return lines.join('\n')
}

const workLinkSchema = Type.Object(
  {
    kind: Type.Union(
      WORK_LINK_KINDS.map((kind) => Type.Literal(kind)),
      { description: 'run, review, or document.' },
    ),
    id: Type.String({
      description: 'The run_id, review item_id, or doc_id this follow_up waits on.',
      minLength: 1,
      maxLength: MAX_REF_CHARS,
    }),
    sub: Type.Optional(
      Type.String({ description: 'Review kind, for a review link.', maxLength: MAX_REF_CHARS }),
    ),
  },
  { description: 'Optional server object a follow_up waits on; enables action=check.' },
)

const workStateParameters = Type.Union([
  Type.Object({
    action: Type.Literal('list'),
    status: Type.Optional(
      Type.Union([Type.Literal('open'), Type.Literal('done'), Type.Literal('all')], {
        description: 'Filter threads; defaults to open.',
      }),
    ),
  }),
  Type.Object({
    action: Type.Literal('add'),
    kind: Type.Union(
      WORK_THREAD_KINDS.map((kind) => Type.Literal(kind)),
      { description: 'hypothesis, follow_up, decision, or note.' },
    ),
    title: Type.String({ description: 'Short thread title.', minLength: 1, maxLength: MAX_TITLE_CHARS }),
    detail: Type.Optional(
      Type.String({ description: 'Rationale, evidence, or next step.', maxLength: MAX_DETAIL_CHARS }),
    ),
    refs: Type.Optional(
      Type.Array(Type.String({ maxLength: MAX_REF_CHARS }), {
        description: 'Evidence ids, doc ids, or run ids this thread rests on.',
        maxItems: MAX_REFS,
      }),
    ),
    link: Type.Optional(workLinkSchema),
  }),
  Type.Object({
    action: Type.Literal('update'),
    id: Type.String({ description: 'Thread id, such as wt-12ab34cd.', pattern: '^wt-[0-9a-f]{8}$' }),
    title: Type.Optional(Type.String({ minLength: 1, maxLength: MAX_TITLE_CHARS })),
    detail: Type.Optional(Type.String({ maxLength: MAX_DETAIL_CHARS })),
    status: Type.Optional(Type.Union([Type.Literal('open'), Type.Literal('done')])),
    refs: Type.Optional(Type.Array(Type.String({ maxLength: MAX_REF_CHARS }), { maxItems: MAX_REFS })),
    link: Type.Optional(workLinkSchema),
  }),
  Type.Object({
    action: Type.Literal('close'),
    id: Type.String({ description: 'Thread id to mark done.', pattern: '^wt-[0-9a-f]{8}$' }),
  }),
  Type.Object({
    action: Type.Literal('check'),
  }),
])

/** The model-facing cross-session work ledger tool. */
export function workStateTool() {
  return defineTool({
    name: WORK_STATE_TOOL_NAME,
    label: WORK_STATE_TOOL_NAME,
    description:
      'Read and update the durable cross-session research work ledger: the active objective plus hypothesis/follow_up/decision/note threads. Unlike a session goal, this survives new sessions and is injected at startup. A follow_up can link to a run/review/document and action=check reconciles it against the server. This is mutable research state, not library evidence and not a stable lesson (those belong in memory).',
    promptGuidelines: [
      'Use work_state action="add" to record research work in progress — a design hypothesis, a pending follow-up (synthesis/activity result, human review), or a decision with its rationale and evidence refs. Stable preferences/lessons go to memory instead; do not double-store.',
      'For a follow_up that waits on server work, set link {kind:"run"|"review"|"document", id} (plus sub=review kind for a review). action="check" reads the current status read-only: a done run closes its follow_up, a failed run or undecided review is annotated and left open for you to act on.',
      'Use action="list" to resume context, "update" to refine, "close" when resolved. The goal tool mirrors its active objective here automatically (begin/update/complete/cancel).',
      'This ledger is context, not source evidence: cite library facts through capability tools and [[ev:...]] markers, not from memory of this ledger.',
    ],
    parameters: workStateParameters,
    ...toolRenderers(WORK_STATE_TOOL_NAME),
    async execute(_toolCallId, params) {
      if (params.action === 'list') {
        const state = await readWorkState()
        const filter = params.status ?? 'open'
        const threads =
          filter === 'all' ? state.threads : state.threads.filter((t) => t.status === filter)
        const details = {
          action: 'list' as const,
          path: workStateFilePath(),
          active_goal: state.active_goal,
          items: threads,
          count: threads.length,
        }
        return { content: [{ type: 'text', text: JSON.stringify(details) }], details }
      }
      if (params.action === 'add') {
        const thread = await addWorkThread({
          kind: params.kind,
          title: params.title,
          detail: params.detail,
          refs: params.refs,
          link: params.link,
        })
        const details = { action: 'add' as const, path: workStateFilePath(), ...thread, message: `recorded ${thread.kind} ${thread.id}` }
        return { content: [{ type: 'text', text: JSON.stringify(details) }], details }
      }
      if (params.action === 'update') {
        const thread = await updateWorkThread(params.id, {
          title: params.title,
          detail: params.detail,
          status: params.status,
          refs: params.refs,
          link: params.link,
        })
        const details = { action: 'update' as const, path: workStateFilePath(), ...thread, message: `updated ${thread.id}` }
        return { content: [{ type: 'text', text: JSON.stringify(details) }], details }
      }
      if (params.action === 'close') {
        const thread = await closeWorkThread(params.id)
        const details = { action: 'close' as const, path: workStateFilePath(), ...thread, message: `closed ${thread.id}` }
        return { content: [{ type: 'text', text: JSON.stringify(details) }], details }
      }
      if (params.action === 'check') {
        // Lazy import keeps workState (storage) free of a static cycle with the
        // reconciler, which reads the server and calls back into storage.
        const { reconcileWorkThreads } = await import('./workReconcile.js')
        const results = await reconcileWorkThreads()
        const details = {
          action: 'check' as const,
          path: workStateFilePath(),
          items: results,
          count: results.length,
          closed: results.filter((result) => result.outcome === 'closed').length,
          message:
            results.length === 0
              ? 'no open follow_up has a link to check'
              : `checked ${results.length} linked follow_up(s)`,
        }
        return { content: [{ type: 'text', text: JSON.stringify(details) }], details }
      }
      throw new Error(`work_state action must be one of: ${WORK_STATE_ACTIONS.join(', ')}`)
    },
  })
}

/** Register the work-state tool. */
export function registerWorkStateTools(pi: ExtensionAPI): void {
  pi.registerTool(workStateTool())
}