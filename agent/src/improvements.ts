import { randomUUID } from 'node:crypto'
import { existsSync } from 'node:fs'
import { mkdir, readFile, rename, unlink, writeFile } from 'node:fs/promises'
import { dirname, join, resolve } from 'node:path'

import {
  defineTool,
  getAgentDir,
  type ExtensionAPI,
} from '@earendil-works/pi-coding-agent'
import { Type } from 'typebox'

const IMPROVEMENTS_FILE_NAME = 'IMPROVEMENTS.json'
const MAX_IMPROVEMENTS = 50
const MAX_FILES = 32
const MAX_TITLE_CHARS = 120
const MAX_TEXT_CHARS = 4_000
const MAX_RISK_CHARS = 1_000

export const IMPROVEMENT_TOOL_NAME = 'suggest_improvement'
export const IMPROVEMENT_TOOL_NAMES = [IMPROVEMENT_TOOL_NAME] as const

export const IMPROVEMENT_AREAS = [
  'pipeline',
  'capability',
  'agent',
  'ui',
  'docs',
  'other',
] as const
export type ImprovementArea = (typeof IMPROVEMENT_AREAS)[number]

export const IMPROVEMENT_ACTIONS = ['propose', 'list', 'complete'] as const
export type ImprovementAction = (typeof IMPROVEMENT_ACTIONS)[number]

export type ImprovementStatus = 'approved' | 'rejected' | 'implemented'

export interface ImprovementInput {
  title: string
  area: ImprovementArea
  problem: string
  change: string
  rationale?: string
  risk?: string
  files?: string[]
}

export interface ImprovementRecord extends ImprovementInput {
  id: string
  project: string
  status: ImprovementStatus
  created_at: string
  updated_at: string
  completed_at?: string
  completion_note?: string
}

export interface ImprovementStore {
  version: 1
  items: ImprovementRecord[]
}

export interface ImprovementDecision {
  path: string
  id: string
  approved: boolean
  executable: boolean
  status: ImprovementStatus
  message: string
}

export interface ImprovementList {
  path: string
  items: ImprovementRecord[]
}

export interface ImprovementCompletion {
  path: string
  id: string
  status: ImprovementStatus
  already_completed: boolean
}

export interface ImprovementToolDetails {
  action: ImprovementAction
  path: string
  id?: string
  approved?: boolean
  executable?: boolean
  status?: ImprovementStatus
  items?: ImprovementRecord[]
  message?: string
  already_completed?: boolean
}

/** Local suggestion log; override with MBFORGE_IMPROVEMENTS_FILE in tests or custom layouts. */
export function improvementsFilePath(): string {
  const override = process.env.MBFORGE_IMPROVEMENTS_FILE?.trim()
  return override ? resolve(override) : join(getAgentDir(), IMPROVEMENTS_FILE_NAME)
}

function cleanText(
  value: string,
  field: string,
  max: number,
  singleLine = false,
): string {
  let text = value.replace(/\r\n?/g, '\n').trim()
  if (singleLine) text = text.replace(/\s+/g, ' ')
  if (!text) throw new Error(`${field} must not be empty`)
  if (text.length > max) {
    throw new Error(`${field} must be at most ${max} characters`)
  }
  if (/[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f]/.test(text)) {
    throw new Error(`${field} contains control characters`)
  }
  return text
}

function normalizeInput(input: ImprovementInput): ImprovementInput {
  if (!(IMPROVEMENT_AREAS as readonly string[]).includes(input.area)) {
    throw new Error(`area must be one of: ${IMPROVEMENT_AREAS.join(', ')}`)
  }
  const files = (input.files ?? [])
    .map((file) => cleanText(file, 'file', 300, true))
    .filter((file, index, all) => all.indexOf(file) === index)
    .slice(0, MAX_FILES)
  return {
    title: cleanText(input.title, 'title', MAX_TITLE_CHARS, true),
    area: input.area,
    problem: cleanText(input.problem, 'problem', MAX_TEXT_CHARS),
    change: cleanText(input.change, 'change', MAX_TEXT_CHARS),
    rationale: input.rationale
      ? cleanText(input.rationale, 'rationale', MAX_TEXT_CHARS)
      : '',
    risk: input.risk
      ? cleanText(input.risk, 'risk', MAX_RISK_CHARS)
      : '',
    files,
  }
}

async function writeStore(path: string, store: ImprovementStore): Promise<void> {
  await mkdir(dirname(path), { recursive: true, mode: 0o700 })
  const temporary = `${path}.${process.pid}.${Date.now()}.tmp`
  try {
    await writeFile(temporary, `${JSON.stringify(store, null, 2)}\n`, {
      encoding: 'utf8',
      mode: 0o600,
    })
    await rename(temporary, path)
  } catch (error) {
    try {
      await unlink(temporary)
    } catch {
      // Best effort cleanup; preserve the original write error.
    }
    throw error
  }
}

async function readStore(path: string): Promise<ImprovementStore> {
  if (!existsSync(path)) return { version: 1, items: [] }
  const raw = (await readFile(path, 'utf8')).replace(/^\uFEFF/, '')
  if (!raw.trim()) return { version: 1, items: [] }
  let parsed: unknown
  try {
    parsed = JSON.parse(raw)
  } catch (error) {
    throw new Error(`Improvement log is not valid JSON: ${path}`, {
      cause: error,
    })
  }
  if (typeof parsed !== 'object' || parsed === null) {
    throw new Error(`Improvement log has an invalid shape: ${path}`)
  }
  const rows = (parsed as { items?: unknown }).items
  if (!Array.isArray(rows)) {
    throw new Error(`Improvement log has an invalid shape: ${path}`)
  }
  const items = rows.filter((item): item is ImprovementRecord => {
    if (typeof item !== 'object' || item === null) return false
    const row = item as Partial<ImprovementRecord>
    return (
      typeof row.id === 'string' &&
      typeof row.title === 'string' &&
      typeof row.status === 'string'
    )
  })
  return { version: 1, items }
}

let writeChain: Promise<unknown> = Promise.resolve()

function serialize<T>(operation: () => Promise<T>): Promise<T> {
  const run = writeChain.then(operation)
  writeChain = run.then(
    () => undefined,
    () => undefined,
  )
  return run
}

export interface ProposeImprovementOptions {
  project: string
  canEdit: boolean
  hasUI: boolean
  confirm: (title: string, message: string) => Promise<boolean>
}

/** Readable confirmation body: title, metadata, then one indented block per field. */
function formatImprovementPrompt(
  suggestion: ImprovementInput,
  project: string,
): string {
  const lines = [
    suggestion.title,
    `${suggestion.area} · ${project}`,
  ]
  const block = (label: string, value: string): void => {
    if (!value) return
    lines.push('', label, ...value.split('\n').map((line) => `  ${line}`))
  }
  block('问题', suggestion.problem)
  block('改动', suggestion.change)
  block('收益', suggestion.rationale ?? '')
  block('风险', suggestion.risk ?? '')
  const files = suggestion.files ?? []
  if (files.length > 0) {
    lines.push('', '涉及', ...files.map((file) => `  ${file}`))
  }
  return lines.join('\n')
}

/**
 * Record one suggestion only after the user explicitly confirms it.
 *
 * The tool never edits code itself. An approved result tells the agent it may
 * implement the stated change with the active repository tools; a declined or
 * non-executable result must stop the agent.
 */
export async function proposeImprovement(
  input: ImprovementInput,
  options: ProposeImprovementOptions,
): Promise<ImprovementDecision> {
  if (!options.hasUI) {
    throw new Error(
      'suggestion approval requires an interactive session; run the agent in its TUI',
    )
  }
  const suggestion = normalizeInput(input)
  const path = improvementsFilePath()
  const message = formatImprovementPrompt(suggestion, options.project)
  const approved = await options.confirm('Apply improvement?', message)
  const now = new Date().toISOString()
  const record: ImprovementRecord = {
    ...suggestion,
    id: `imp-${randomUUID().slice(0, 8)}`,
    project: options.project,
    status: approved ? 'approved' : 'rejected',
    created_at: now,
    updated_at: now,
  }

  return serialize(async () => {
    const store = await readStore(path)
    const next: ImprovementStore = {
      version: 1,
      items: [record, ...store.items].slice(0, MAX_IMPROVEMENTS),
    }
    await writeStore(path, next)
    return {
      path,
      id: record.id,
      approved,
      executable: approved && options.canEdit,
      status: record.status,
      message: approved
        ? options.canEdit
          ? 'Approved. Implement exactly this change with the repository tools, verify it, then call action=complete.'
          : 'Approved, but repository edit tools are inactive. Ask the user to switch to dev mode; do not claim implementation.'
        : 'Declined. Do not implement this change.',
    }
  })
}

/** Recent suggestions, newest first. */
export async function listImprovements(): Promise<ImprovementList> {
  const path = improvementsFilePath()
  const store = await readStore(path)
  return { path, items: store.items }
}

/** Mark an approved suggestion as implemented; rejected items cannot be completed. */
export async function completeImprovement(
  id: string,
  note = '',
): Promise<ImprovementCompletion> {
  const path = improvementsFilePath()
  const normalizedId = cleanText(id, 'id', 40, true)
  const normalizedNote = note ? cleanText(note, 'note', 500) : ''
  return serialize(async () => {
    const store = await readStore(path)
    const item = store.items.find((entry) => entry.id === normalizedId)
    if (!item) throw new Error(`Improvement not found: ${normalizedId}`)
    if (item.status === 'rejected') {
      throw new Error(`Improvement was declined: ${normalizedId}`)
    }
    if (item.status === 'implemented') {
      return {
        path,
        id: item.id,
        status: item.status,
        already_completed: true,
      }
    }
    if (item.status !== 'approved') {
      throw new Error(`Improvement is not approved: ${normalizedId}`)
    }
    const now = new Date().toISOString()
    item.status = 'implemented'
    item.updated_at = now
    item.completed_at = now
    item.completion_note = normalizedNote
    await writeStore(path, store)
    return {
      path,
      id: item.id,
      status: item.status,
      already_completed: false,
    }
  })
}

const improvementParameters = Type.Union([
  Type.Object({
    action: Type.Literal('propose'),
    title: Type.String({
      description: 'Short name of the proposed improvement.',
      minLength: 1,
      maxLength: MAX_TITLE_CHARS,
    }),
    area: Type.Union(
      IMPROVEMENT_AREAS.map((area) => Type.Literal(area)),
      {
        description:
          'pipeline, capability, agent, ui, docs, or other.',
      },
    ),
    problem: Type.String({
      description: 'Concrete observed problem or gap.',
      minLength: 1,
      maxLength: MAX_TEXT_CHARS,
    }),
    change: Type.String({
      description: 'Exact proposed change, scoped to the observed problem.',
      minLength: 1,
      maxLength: MAX_TEXT_CHARS,
    }),
    rationale: Type.Optional(
      Type.String({
        description: 'Why this change is worthwhile.',
        maxLength: MAX_TEXT_CHARS,
      }),
    ),
    risk: Type.Optional(
      Type.String({
        description: 'Known risk, compatibility cost, or rollback concern.',
        maxLength: MAX_RISK_CHARS,
      }),
    ),
    files: Type.Optional(
      Type.Array(Type.String({ maxLength: 300 }), {
        description: 'Files or modules expected to change.',
        maxItems: MAX_FILES,
      }),
    ),
  }),
  Type.Object({
    action: Type.Literal('list'),
  }),
  Type.Object({
    action: Type.Literal('complete'),
    id: Type.String({
      description: 'Improvement id to complete, such as imp-12ab34cd.',
      pattern: '^imp-[0-9a-f]{8}$',
    }),
    note: Type.Optional(
      Type.String({
        description: 'Short implementation or verification note.',
        maxLength: 500,
      }),
    ),
  }),
])

/** The single model-facing improvement tool. */
export function improvementTool() {
  return defineTool({
    name: IMPROVEMENT_TOOL_NAME,
    label: IMPROVEMENT_TOOL_NAME,
    description:
      'Propose one concrete improvement to MBForge’s pipeline, capability tools, agent prompt, UI, or docs. The tool asks the user for approval; it never edits code itself. After an approved result, implement only the stated change with repository tools and call action=complete.',
    promptGuidelines: [
      'Use this tool only when a run reveals a concrete, scoped design or tooling gap that the user did not already ask you to change. Do not use it for library data corrections (use propose_review), ordinary requested edits, or speculative refactors.',
      'Call action="propose" with the observed problem, the exact change, the expected benefit, the risk, and the files involved. The tool shows the user a confirmation dialog. Never edit code before it returns approved=true.',
      'If approved=true and executable=true, implement exactly the proposed scope with repository tools, verify it, then call action="complete" with the id and a short verification note. If approved=false, stop and do not implement. If executable=false, tell the user to switch to dev mode; do not claim the change was applied.',
      'Use action="list" to inspect prior suggestions before proposing a duplicate.',
    ],
    parameters: improvementParameters,
    async execute(_toolCallId, params, _signal, _onUpdate, ctx) {
      if (params.action === 'propose') {
        if (!params.title || !params.area || !params.problem || !params.change) {
          throw new Error(
            'suggest_improvement action "propose" requires title, area, problem, and change',
          )
        }
        const result = await proposeImprovement(
          {
            title: params.title,
            area: params.area,
            problem: params.problem,
            change: params.change,
            rationale: params.rationale,
            risk: params.risk,
            files: params.files,
          },
          {
            project: ctx.cwd,
            canEdit: ctx.tools.some(
              (tool) => tool.name === 'edit' || tool.name === 'write',
            ),
            hasUI: ctx.hasUI,
            confirm: (title, message) => ctx.ui.confirm(title, message),
          },
        )
        const details: ImprovementToolDetails = {
          action: 'propose',
          path: result.path,
          id: result.id,
          approved: result.approved,
          executable: result.executable,
          status: result.status,
          message: result.message,
        }
        return {
          content: [{ type: 'text', text: JSON.stringify(details) }],
          details,
        }
      }

      if (params.action === 'list') {
        const result = await listImprovements()
        const details: ImprovementToolDetails = {
          action: 'list',
          path: result.path,
          items: result.items,
        }
        return {
          content: [{ type: 'text', text: JSON.stringify(details) }],
          details,
        }
      }

      if (params.action === 'complete') {
        if (!params.id) {
          throw new Error('suggest_improvement action "complete" requires id')
        }
        const result = await completeImprovement(params.id, params.note)
        const details: ImprovementToolDetails = {
          action: 'complete',
          path: result.path,
          id: result.id,
          status: result.status,
          already_completed: result.already_completed,
        }
        return {
          content: [{ type: 'text', text: JSON.stringify(details) }],
          details,
        }
      }

      throw new Error(
        `suggest_improvement action must be one of: ${IMPROVEMENT_ACTIONS.join(', ')}`,
      )
    },
  })
}

/** Register the model-facing improvement tool and the user-facing /improvements command. */
export function registerImprovementTools(pi: ExtensionAPI): void {
  pi.registerTool(improvementTool())
  pi.registerCommand('improvements', {
    description: 'Show recent agent improvement suggestions',
    handler: async (_args, ctx) => {
      try {
        const { items, path } = await listImprovements()
        if (items.length === 0) {
          ctx.ui.notify(`No improvement suggestions yet: ${path}`, 'info')
          return
        }
        const lines = items.slice(0, 12).map((item) => {
          const mark =
            item.status === 'approved'
              ? '✓'
              : item.status === 'implemented'
                ? '●'
                : '×'
          return `${mark} ${item.id}  ${item.area} · ${item.title}`
        })
        ctx.ui.notify(
          [
            `Improvement suggestions (${items.length}): ${path}`,
            ...lines,
          ].join('\n'),
          'info',
        )
      } catch (error) {
        const message = error instanceof Error ? error.message : String(error)
        ctx.ui.notify(`Improvements unavailable: ${message}`, 'error')
      }
    },
  })
}
