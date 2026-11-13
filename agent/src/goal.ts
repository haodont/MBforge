import { randomUUID } from 'node:crypto'

import {
  defineTool,
  type ExtensionAPI,
  type ExtensionContext,
} from '@earendil-works/pi-coding-agent'
import { Type } from 'typebox'

import { collectTranscript } from './review.js'
import { toolRenderers } from './toolRender.js'

export const GOAL_TOOL_NAME = 'goal'
export const GOAL_TOOL_NAMES = [GOAL_TOOL_NAME] as const
export const GOAL_ENTRY_TYPE = 'mbforge-goal'

export type RequirementStatus = 'pending' | 'doing' | 'done' | 'blocked'
export type GoalStatus = 'active' | 'paused'

export interface GoalRequirement {
  id: string
  text: string
  status: RequirementStatus
  evidence?: string
  note?: string
}

export interface GoalDefinition {
  id: string
  title: string
  objective: string
  requirements: GoalRequirement[]
  constraints: string[]
  non_goals: string[]
  status: GoalStatus
  created_at: string
}

export interface GoalReviewJob {
  goalId: string
  cwd: string
  transcript: string
}

interface GoalEventData {
  action:
    | 'begin'
    | 'update'
    | 'progress'
    | 'complete'
    | 'cancel'
    | 'supersede'
    | 'tool'
  goal_id: string
  goal?: GoalDefinition
  requirements?: GoalRequirement[]
  summary?: string
  verification?: string[]
  risks?: string[]
  unmet?: string[]
  reason?: string
  tool?: string
  input?: string
  input_digest?: string
  status?: 'ok' | 'error'
  error?: string
  at: string
}

export interface GoalToolOptions {
  appendEntry: (data: GoalEventData) => void
  enqueueReview: (job: GoalReviewJob) => Promise<void> | void
  getActiveGoal: () => string | undefined
  setActiveGoal: (id: string | undefined, ctx: ExtensionContext) => void
  /** Freeze the completed goal's tool trajectory as a regression eval fixture. */
  archiveTrajectory?: (goalId: string, branch: readonly unknown[]) => void
}

const REQUIREMENT_STATUSES: RequirementStatus[] = [
  'pending',
  'doing',
  'done',
  'blocked',
]

function text(value: unknown): string {
  return typeof value === 'string' ? value.trim() : ''
}

function strings(value: unknown): string[] {
  return Array.isArray(value)
    ? value.map(text).filter((item) => item !== '')
    : []
}

function clean(value: string, field: string, max: number): string {
  const result = value.replace(/\r\n?/g, '\n').trim()
  if (!result) throw new Error(`${field} must not be empty`)
  if (result.length > max) {
    throw new Error(`${field} must be at most ${max} characters`)
  }
  return result
}

function cleanList(value: unknown, field: string, max: number): string[] {
  return strings(value).map((item) => clean(item, field, max))
}

function normalizeStatus(value: unknown): RequirementStatus {
  const status = text(value)
  return (REQUIREMENT_STATUSES as string[]).includes(status)
    ? (status as RequirementStatus)
    : 'pending'
}

/** Parse requirements, tolerating the legacy plain-string form. */
function requirementsFromData(value: unknown): GoalRequirement[] {
  if (!Array.isArray(value)) return []
  const result: GoalRequirement[] = []
  for (const [index, item] of value.entries()) {
    if (typeof item === 'string') {
      const trimmed = item.trim()
      if (trimmed)
        result.push({ id: `r${index + 1}`, text: trimmed, status: 'pending' })
      continue
    }
    if (typeof item !== 'object' || item === null) continue
    const record = item as Record<string, unknown>
    const requirementText = text(record.text)
    if (!requirementText) continue
    const evidence = text(record.evidence)
    const note = text(record.note)
    result.push({
      id: text(record.id) || `r${index + 1}`,
      text: requirementText,
      status: normalizeStatus(record.status),
      ...(evidence ? { evidence } : {}),
      ...(note ? { note } : {}),
    })
  }
  return result
}

function goalFromData(value: unknown): GoalDefinition | undefined {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) {
    return undefined
  }
  const record = value as Record<string, unknown>
  const id = text(record.id)
  const title = text(record.title)
  const objective = text(record.objective)
  if (!id || !objective) return undefined
  return {
    id,
    title: title || objective.slice(0, 60),
    objective,
    requirements: requirementsFromData(record.requirements),
    constraints: strings(record.constraints),
    non_goals: strings(record.non_goals),
    status: text(record.status) === 'paused' ? 'paused' : 'active',
    created_at: text(record.created_at) || new Date().toISOString(),
  }
}

function customGoal(
  entry: unknown,
): { data: Record<string, unknown> } | undefined {
  if (typeof entry !== 'object' || entry === null || Array.isArray(entry)) {
    return undefined
  }
  const record = entry as Record<string, unknown>
  if (
    record.type !== 'custom' ||
    record.customType !== GOAL_ENTRY_TYPE ||
    typeof record.data !== 'object' ||
    record.data === null ||
    Array.isArray(record.data)
  ) {
    return undefined
  }
  return { data: record.data as Record<string, unknown> }
}

function applyProgress(goal: GoalDefinition, updates: GoalRequirement[]): void {
  for (const update of updates) {
    const existing = goal.requirements.find((item) => item.id === update.id)
    if (existing) Object.assign(existing, update)
    else goal.requirements.push({ ...update })
  }
}

/** Find a goal's begin entry and apply later updates/progress in the branch. */
export function goalStateFromBranch(
  branch: readonly unknown[],
  goalId: string,
): { goal: GoalDefinition; startIndex: number } | undefined {
  let startIndex = -1
  for (let index = branch.length - 1; index >= 0; index -= 1) {
    const entry = customGoal(branch[index])
    if (!entry) continue
    if (
      text(entry.data.action) !== 'begin' ||
      text(entry.data.goal_id) !== goalId
    ) {
      continue
    }
    startIndex = index
    break
  }
  if (startIndex < 0) return undefined
  const begin = customGoal(branch[startIndex])
  const goal = goalFromData(begin?.data.goal)
  if (!goal) return undefined
  for (let index = startIndex + 1; index < branch.length; index += 1) {
    const entry = customGoal(branch[index])
    if (!entry) continue
    if (text(entry.data.goal_id) !== goalId) continue
    const action = text(entry.data.action)
    if (action === 'update') {
      const update = goalFromData(entry.data.goal)
      if (update) Object.assign(goal, update, { id: goal.id })
    } else if (action === 'progress') {
      applyProgress(goal, requirementsFromData(entry.data.requirements))
    }
  }
  return { goal, startIndex }
}

function requirementLine(requirement: GoalRequirement): string {
  const evidence = requirement.evidence
    ? ` (evidence: ${requirement.evidence})`
    : ''
  const note = requirement.note ? ` — ${requirement.note}` : ''
  return `- [${requirement.status}] ${requirement.id}: ${requirement.text}${evidence}${note}`
}

function goalDefinitionText(goal: GoalDefinition): string {
  const done = goal.requirements.filter((item) => item.status === 'done').length
  const requirements =
    goal.requirements.length > 0
      ? `Requirements (${done}/${goal.requirements.length} done):\n${goal.requirements
          .map(requirementLine)
          .join('\n')}`
      : 'Requirements: none yet — decompose the objective with goal action=progress.'
  return [
    `Goal ${goal.id}: ${goal.title}${goal.status === 'paused' ? ' (paused)' : ''}`,
    `Objective: ${goal.objective}`,
    requirements,
    goal.constraints.length > 0
      ? `Constraints:\n${goal.constraints.map((item) => `- ${item}`).join('\n')}`
      : '',
    goal.non_goals.length > 0
      ? `Non-goals:\n${goal.non_goals.map((item) => `- ${item}`).join('\n')}`
      : '',
  ]
    .filter((line) => line !== '')
    .join('\n')
}

/**
 * Compact active-goal contract re-injected on every turn. Custom branch entries
 * are never model-visible and compaction summarizes away the original tool
 * result, so this keeps the living plan in context for the whole task.
 */
export function goalContractPrompt(goal: GoalDefinition): string {
  return (
    `## Active goal contract\n\n${goalDefinitionText(goal)}\n\n` +
    'Keep the plan live: use goal action=progress to mark requirements doing/done/blocked ' +
    'with evidence as you work, and action=update status=paused if you must stop. Call ' +
    'complete when the requirements are done; report any unmet ones honestly rather than ' +
    'claiming success.'
  )
}

export function goalTranscript(
  goal: GoalDefinition,
  branch: readonly unknown[],
  startIndex: number,
): string {
  const definition = goalDefinitionText(goal)
  const tools = branch
    .slice(startIndex + 1)
    .map((entry) => customGoal(entry))
    .filter((entry): entry is { data: Record<string, unknown> } =>
      Boolean(entry),
    )
    .filter((entry) => text(entry.data.action) === 'tool')
    .slice(-40)
    .map((entry) => {
      const tool = text(entry.data.tool) || 'tool'
      const status = text(entry.data.status) || 'unknown'
      const input = text(entry.data.input)
      return `- ${tool} ${status}${input ? ` input=${input}` : ''}`
    })
  const toolIndex = tools.length > 0 ? `Tool index:\n${tools.join('\n')}` : ''
  const conversation = collectTranscript(branch.slice(startIndex + 1))
  return [
    definition,
    toolIndex,
    `Conversation:\n${conversation || '(no messages)'}`,
  ]
    .filter((part) => part !== '')
    .join('\n\n')
}

const goalIdSchema = Type.Optional(
  Type.String({
    description:
      'Goal id for update/progress/complete/cancel. Defaults to the active goal.',
    maxLength: 64,
  }),
)

const goalTitleSchema = Type.String({
  description: 'Short goal title. Defaults to the objective when omitted.',
  minLength: 1,
  maxLength: 160,
})

const goalObjectiveSchema = Type.String({
  description: 'One-sentence outcome the user asked for.',
  minLength: 1,
  maxLength: 2_000,
})

const requirementStatusSchema = Type.Union([
  Type.Literal('pending'),
  Type.Literal('doing'),
  Type.Literal('done'),
  Type.Literal('blocked'),
])

const goalConstraintsSchema = Type.Array(Type.String({ maxLength: 2_000 }), {
  description: 'Things that must not change or must be preserved.',
  maxItems: 10,
})

const goalNonGoalsSchema = Type.Array(Type.String({ maxLength: 2_000 }), {
  description: 'Explicitly excluded work.',
  maxItems: 10,
})

const goalParameters = Type.Union([
  Type.Object({
    action: Type.Literal('begin'),
    objective: goalObjectiveSchema,
    title: Type.Optional(goalTitleSchema),
    requirements: Type.Optional(
      Type.Array(Type.String({ maxLength: 2_000 }), {
        description:
          'Optional initial requirements; decompose further with progress as you work.',
        maxItems: 20,
      }),
    ),
    constraints: Type.Optional(goalConstraintsSchema),
    non_goals: Type.Optional(goalNonGoalsSchema),
  }),
  Type.Object({
    action: Type.Literal('update'),
    id: goalIdSchema,
    title: Type.Optional(goalTitleSchema),
    objective: Type.Optional(goalObjectiveSchema),
    constraints: Type.Optional(goalConstraintsSchema),
    non_goals: Type.Optional(goalNonGoalsSchema),
    status: Type.Optional(
      Type.Union([Type.Literal('active'), Type.Literal('paused')], {
        description:
          'Pause the goal (status=paused) or resume it (status=active).',
      }),
    ),
  }),
  Type.Object({
    action: Type.Literal('progress'),
    id: goalIdSchema,
    requirements: Type.Array(
      Type.Object({
        id: Type.Optional(
          Type.String({
            description: 'Existing requirement id to update.',
            maxLength: 32,
          }),
        ),
        text: Type.Optional(
          Type.String({
            description: 'Requirement text; a new id is assigned when adding.',
            maxLength: 2_000,
          }),
        ),
        status: Type.Optional(requirementStatusSchema),
        evidence: Type.Optional(
          Type.String({
            description:
              'Evidence ref proving done (evidence id, test result).',
            maxLength: 1_000,
          }),
        ),
        note: Type.Optional(
          Type.String({
            description: 'Why blocked, or other context.',
            maxLength: 1_000,
          }),
        ),
      }),
      {
        minItems: 1,
        maxItems: 20,
        description:
          'Requirement upserts: mark status/evidence by id, or add new ones with text.',
      },
    ),
  }),
  Type.Object({
    action: Type.Literal('complete'),
    id: goalIdSchema,
    summary: Type.Optional(
      Type.String({
        description: 'Optional short completion summary.',
        maxLength: 4_000,
      }),
    ),
    verification: Type.Optional(
      Type.Array(Type.String({ maxLength: 1_000 }), {
        description: 'Commands/tests and their results.',
        maxItems: 20,
      }),
    ),
    risks: Type.Optional(
      Type.Array(Type.String({ maxLength: 1_000 }), {
        description: 'Residual risks or unfinished work.',
        maxItems: 10,
      }),
    ),
  }),
  Type.Object({
    action: Type.Literal('cancel'),
    id: goalIdSchema,
    reason: Type.Optional(
      Type.String({
        description: 'Why the goal is cancelled.',
        maxLength: 1_000,
      }),
    ),
  }),
])

function activeGoalId(options: GoalToolOptions, requested?: string): string {
  const id = requested?.trim() || options.getActiveGoal()
  if (!id) throw new Error('no active goal; call action=begin first')
  return id
}

function requirementState(goal: GoalDefinition) {
  return goal.requirements.map((requirement) => ({ ...requirement }))
}

export function goalTool(options: GoalToolOptions) {
  return defineTool({
    name: GOAL_TOOL_NAME,
    label: GOAL_TOOL_NAME,
    description:
      'Track a user goal as a living plan. begin with just an objective (requirements optional); progress marks requirements doing/done/blocked with evidence; update edits scope or pauses/resumes; complete closes it (optionally with a summary) and queues a read-only background review. Lighter than a contract: decompose as you work instead of upfront.',
    promptGuidelines: [
      'Before non-trivial work, call goal action=begin with the objective; add initial requirements only if they are already clear. Do not use a goal for trivial conversation or a one-line status read.',
      'As you work, call action=progress to mark requirements doing/done/blocked and attach evidence (an evidence id or test result). Add new requirements with text when the plan grows. Keep the plan honest.',
      'When scope changes call action=update; pause with status=paused if interrupted and resume with status=active. If the user cancels or replaces the task, call action=cancel.',
      'Call action=complete when the requirements are done; a summary is optional. Completion lists any unmet requirements and queues a background review — do not wait for it or call review_task for the same goal.',
    ],
    parameters: goalParameters,
    ...toolRenderers(GOAL_TOOL_NAME),
    async execute(_toolCallId, params, _signal, _onUpdate, ctx) {
      const branch = ctx.sessionManager.getBranch()
      const now = new Date().toISOString()

      if (params.action === 'begin') {
        if (options.getActiveGoal()) {
          throw new Error(
            'an active goal already exists; complete or cancel it before beginning another',
          )
        }
        const id = `goal-${randomUUID().slice(0, 8)}`
        const objective = clean(params.objective, 'objective', 2_000)
        const goal: GoalDefinition = {
          id,
          title: params.title?.trim()
            ? clean(params.title, 'title', 160)
            : objective.length > 60
              ? `${objective.slice(0, 57)}…`
              : objective,
          objective,
          requirements: (params.requirements ?? []).map((item, index) => ({
            id: `r${index + 1}`,
            text: clean(item, 'requirement', 2_000),
            status: 'pending' as const,
          })),
          constraints: cleanList(params.constraints, 'constraint', 2_000),
          non_goals: cleanList(params.non_goals, 'non-goal', 2_000),
          status: 'active',
          created_at: now,
        }
        options.appendEntry({ action: 'begin', goal_id: id, goal, at: now })
        options.setActiveGoal(id, ctx)
        return {
          content: [
            { type: 'text', text: JSON.stringify({ action: 'begin', goal }) },
          ],
          details: { action: 'begin', goal },
        }
      }

      if (params.action === 'update') {
        const id = activeGoalId(options, params.id)
        const state = goalStateFromBranch(branch, id)
        if (!state) throw new Error(`goal not found: ${id}`)
        const goal: GoalDefinition = {
          ...state.goal,
          title:
            params.title !== undefined
              ? clean(params.title, 'title', 160)
              : state.goal.title,
          objective:
            params.objective !== undefined
              ? clean(params.objective, 'objective', 2_000)
              : state.goal.objective,
          constraints:
            params.constraints !== undefined
              ? cleanList(params.constraints, 'constraint', 2_000)
              : state.goal.constraints,
          non_goals:
            params.non_goals !== undefined
              ? cleanList(params.non_goals, 'non-goal', 2_000)
              : state.goal.non_goals,
          status: params.status ?? state.goal.status,
        }
        options.appendEntry({ action: 'update', goal_id: id, goal, at: now })
        if (id === options.getActiveGoal()) {
          options.setActiveGoal(id, ctx)
        }
        return {
          content: [
            { type: 'text', text: JSON.stringify({ action: 'update', goal }) },
          ],
          details: { action: 'update', goal },
        }
      }

      if (params.action === 'progress') {
        const id = activeGoalId(options, params.id)
        const state = goalStateFromBranch(branch, id)
        if (!state) throw new Error(`goal not found: ${id}`)
        const requirements = requirementState(state.goal)
        let nextIndex = requirements.length
        const updates: GoalRequirement[] = []
        for (const raw of params.requirements) {
          const reqId = raw.id?.trim()
          const requirementText = raw.text?.trim()
          if (reqId) {
            const existing = requirements.find((item) => item.id === reqId)
            if (!existing) throw new Error(`unknown requirement: ${reqId}`)
            if (requirementText)
              existing.text = clean(requirementText, 'requirement', 2_000)
            if (raw.status) existing.status = raw.status
            if (raw.evidence !== undefined)
              existing.evidence = raw.evidence.trim() || undefined
            if (raw.note !== undefined)
              existing.note = raw.note.trim() || undefined
            updates.push({ ...existing })
          } else if (requirementText) {
            nextIndex += 1
            const added: GoalRequirement = {
              id: `r${nextIndex}`,
              text: clean(requirementText, 'requirement', 2_000),
              status: raw.status ?? 'pending',
              ...(raw.evidence?.trim()
                ? { evidence: raw.evidence.trim() }
                : {}),
              ...(raw.note?.trim() ? { note: raw.note.trim() } : {}),
            }
            requirements.push(added)
            updates.push({ ...added })
          } else {
            throw new Error(
              'each progress item needs an id (to update) or text (to add)',
            )
          }
        }
        options.appendEntry({
          action: 'progress',
          goal_id: id,
          requirements: updates,
          at: now,
        })
        const done = requirements.filter(
          (item) => item.status === 'done',
        ).length
        return {
          content: [
            {
              type: 'text',
              text: JSON.stringify({
                action: 'progress',
                goal_id: id,
                done,
                total: requirements.length,
                requirements,
              }),
            },
          ],
          details: {
            action: 'progress',
            goal_id: id,
            done,
            total: requirements.length,
            requirements,
          },
        }
      }

      if (params.action === 'cancel') {
        const id = activeGoalId(options, params.id)
        options.appendEntry({
          action: 'cancel',
          goal_id: id,
          reason: params.reason?.trim() ?? '',
          at: now,
        })
        options.setActiveGoal(undefined, ctx)
        return {
          content: [
            {
              type: 'text',
              text: JSON.stringify({ action: 'cancel', goal_id: id }),
            },
          ],
          details: { action: 'cancel', goal_id: id },
        }
      }

      const id = activeGoalId(options, params.id)
      const state = goalStateFromBranch(branch, id)
      if (!state) throw new Error(`goal not found: ${id}`)
      const unmet = state.goal.requirements.filter(
        (item) => item.status !== 'done',
      )
      const summary = params.summary?.trim()
        ? clean(params.summary, 'summary', 4_000)
        : ''
      const verification = cleanList(params.verification, 'verification', 1_000)
      const risks = cleanList(params.risks, 'risk', 1_000)
      const completion = [
        summary ? `Summary: ${summary}` : '',
        verification.length > 0
          ? `Verification:\n${verification.map((item) => `- ${item}`).join('\n')}`
          : '',
        risks.length > 0
          ? `Residual risks:\n${risks.map((item) => `- ${item}`).join('\n')}`
          : '',
        unmet.length > 0
          ? `Unmet requirements:\n${unmet.map(requirementLine).join('\n')}`
          : '',
      ]
        .filter((line) => line !== '')
        .join('\n')
      const transcript = `${goalTranscript(state.goal, branch, state.startIndex)}\n\nCompletion:\n${completion || '(no summary)'}`
      options.appendEntry({
        action: 'complete',
        goal_id: id,
        summary,
        verification,
        risks,
        unmet: unmet.map((item) => item.id),
        at: now,
      })
      await options.enqueueReview({ goalId: id, cwd: ctx.cwd, transcript })
      options.setActiveGoal(undefined, ctx)
      options.archiveTrajectory?.(id, branch)
      return {
        content: [
          {
            type: 'text',
            text: JSON.stringify({
              action: 'complete',
              goal_id: id,
              review_queued: true,
              unmet: unmet.map((item) => ({
                id: item.id,
                text: item.text,
                status: item.status,
              })),
            }),
          },
        ],
        details: {
          action: 'complete',
          goal_id: id,
          review_queued: true,
          unmet: unmet.map((item) => ({
            id: item.id,
            text: item.text,
            status: item.status,
          })),
        },
      }
    },
  })
}

/** Rebuild the active goal after a resume or branch switch. A paused goal stays active. */
export function activeGoalFromBranch(
  branch: readonly unknown[],
): string | undefined {
  let active: string | undefined
  for (const entry of branch) {
    const custom = customGoal(entry)
    if (!custom) continue
    const action = text(custom.data.action)
    const id = text(custom.data.goal_id)
    if (!id) continue
    if (action === 'begin') active = id
    else if (
      action === 'complete' ||
      action === 'cancel' ||
      action === 'supersede'
    ) {
      if (active === id) active = undefined
    }
  }
  return active
}

/** Register the goal tool; the extension owns capture and review queue wiring. */
export function registerGoalTool(
  pi: ExtensionAPI,
  options: Omit<GoalToolOptions, 'appendEntry'>,
): void {
  pi.registerTool(
    goalTool({
      ...options,
      appendEntry: (data) => pi.appendEntry(GOAL_ENTRY_TYPE, data),
    }),
  )
}
