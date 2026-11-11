import { randomUUID } from 'node:crypto'

import {
  defineTool,
  type ExtensionAPI,
} from '@earendil-works/pi-coding-agent'
import { Type } from 'typebox'

import { collectTranscript } from './review.js'

export const GOAL_TOOL_NAME = 'goal'
export const GOAL_TOOL_NAMES = [GOAL_TOOL_NAME] as const
export const GOAL_ENTRY_TYPE = 'mbforge-goal'

export interface GoalDefinition {
  id: string
  title: string
  objective: string
  requirements: string[]
  acceptance: string[]
  constraints: string[]
  non_goals: string[]
  created_at: string
}

export interface GoalReviewJob {
  goalId: string
  cwd: string
  transcript: string
}

interface GoalEventData {
  action: 'begin' | 'update' | 'complete' | 'cancel' | 'supersede' | 'tool'
  goal_id: string
  goal?: GoalDefinition
  summary?: string
  verification?: string[]
  risks?: string[]
  reason?: string
  tool?: string
  input?: string
  input_digest?: string
  status?: 'ok' | 'error'
  artifact?: string
  error?: string
  at: string
}

export interface GoalToolOptions {
  appendEntry: (data: GoalEventData) => void
  enqueueReview: (job: GoalReviewJob) => Promise<void> | void
  getActiveGoal: () => string | undefined
  setActiveGoal: (id: string | undefined) => void
}

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

function goalFromData(value: unknown): GoalDefinition | undefined {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) {
    return undefined
  }
  const record = value as Record<string, unknown>
  const id = text(record.id)
  const title = text(record.title)
  const objective = text(record.objective)
  if (!id || !title || !objective) return undefined
  return {
    id,
    title,
    objective,
    requirements: strings(record.requirements),
    acceptance: strings(record.acceptance),
    constraints: strings(record.constraints),
    non_goals: strings(record.non_goals),
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

/** Find a goal's begin entry and apply later updates in the active branch. */
export function goalStateFromBranch(
  branch: readonly unknown[],
  goalId: string,
): { goal: GoalDefinition; startIndex: number } | undefined {
  let startIndex = -1
  for (let index = branch.length - 1; index >= 0; index -= 1) {
    const entry = customGoal(branch[index])
    if (!entry) continue
    if (text(entry.data.action) !== 'begin' || text(entry.data.goal_id) !== goalId) {
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
    if (text(entry.data.action) !== 'update') continue
    const update = goalFromData(entry.data.goal)
    if (update) Object.assign(goal, update, { id: goal.id })
  }
  return { goal, startIndex }
}

export function goalTranscript(
  goal: GoalDefinition,
  branch: readonly unknown[],
  startIndex: number,
): string {
  const definition = [
    `Goal ${goal.id}: ${goal.title}`,
    `Objective: ${goal.objective}`,
    goal.requirements.length > 0
      ? `Requirements:\n${goal.requirements.map((item) => `- ${item}`).join('\n')}`
      : '',
    goal.acceptance.length > 0
      ? `Acceptance:\n${goal.acceptance.map((item) => `- ${item}`).join('\n')}`
      : '',
    goal.constraints.length > 0
      ? `Constraints:\n${goal.constraints.map((item) => `- ${item}`).join('\n')}`
      : '',
    goal.non_goals.length > 0
      ? `Non-goals:\n${goal.non_goals.map((item) => `- ${item}`).join('\n')}`
      : '',
  ]
    .filter((line) => line !== '')
    .join('\n')
  const tools = branch
    .slice(startIndex + 1)
    .map((entry) => customGoal(entry))
    .filter((entry): entry is { data: Record<string, unknown> } => Boolean(entry))
    .filter((entry) => text(entry.data.action) === 'tool')
    .slice(-40)
    .map((entry) => {
      const tool = text(entry.data.tool) || 'tool'
      const status = text(entry.data.status) || 'unknown'
      const input = text(entry.data.input)
      const artifact = text(entry.data.artifact)
      return `- ${tool} ${status}${input ? ` input=${input}` : ''}${artifact ? ` artifact=${artifact}` : ''}`
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
    description: 'Goal id for update/complete/cancel. Defaults to the active goal.',
    maxLength: 64,
  }),
)

const goalTitleSchema = Type.String({
  description: 'Short goal title.',
  minLength: 1,
  maxLength: 160,
})

const goalObjectiveSchema = Type.String({
  description: 'One-sentence outcome the user asked for.',
  minLength: 1,
  maxLength: 2_000,
})

const goalRequirementsSchema = Type.Array(Type.String({ maxLength: 2_000 }), {
  description: 'Verifiable requirements; keep to 1-5.',
  minItems: 1,
  maxItems: 5,
})

const goalAcceptanceSchema = Type.Array(Type.String({ maxLength: 2_000 }), {
  description: 'Evidence that proves each requirement is complete.',
  maxItems: 10,
})

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
    title: goalTitleSchema,
    objective: goalObjectiveSchema,
    requirements: goalRequirementsSchema,
    acceptance: Type.Optional(goalAcceptanceSchema),
    constraints: Type.Optional(goalConstraintsSchema),
    non_goals: Type.Optional(goalNonGoalsSchema),
  }),
  Type.Object({
    action: Type.Literal('update'),
    id: goalIdSchema,
    title: Type.Optional(goalTitleSchema),
    objective: Type.Optional(goalObjectiveSchema),
    requirements: Type.Optional(goalRequirementsSchema),
    acceptance: Type.Optional(goalAcceptanceSchema),
    constraints: Type.Optional(goalConstraintsSchema),
    non_goals: Type.Optional(goalNonGoalsSchema),
  }),
  Type.Object({
    action: Type.Literal('complete'),
    id: goalIdSchema,
    summary: Type.String({
      description: 'Completion summary for complete.',
      minLength: 1,
      maxLength: 4_000,
    }),
    verification: Type.Optional(
      Type.Array(Type.String({ maxLength: 1_000 }), {
        description: 'Commands/tests and their results for complete.',
        maxItems: 20,
      }),
    ),
    risks: Type.Optional(
      Type.Array(Type.String({ maxLength: 1_000 }), {
        description: 'Residual risks or unfinished work for complete.',
        maxItems: 10,
      }),
    ),
  }),
  Type.Object({
    action: Type.Literal('cancel'),
    id: goalIdSchema,
    reason: Type.Optional(
      Type.String({ description: 'Why the goal is cancelled.', maxLength: 1_000 }),
    ),
  }),
])

function normalizeGoal(
  params: {
    title?: string
    objective?: string
    requirements?: string[]
    acceptance?: string[]
    constraints?: string[]
    non_goals?: string[]
  },
  id: string,
  createdAt: string,
): GoalDefinition {
  const requirements = (params.requirements ?? []).map((item) =>
    clean(item, 'requirement', 2_000),
  )
  if (requirements.length === 0) {
    throw new Error('goal begin requires at least one requirement')
  }
  return {
    id,
    title: clean(params.title ?? '', 'title', 160),
    objective: clean(params.objective ?? '', 'objective', 2_000),
    requirements,
    acceptance: (params.acceptance ?? []).map((item) =>
      clean(item, 'acceptance', 2_000),
    ),
    constraints: (params.constraints ?? []).map((item) =>
      clean(item, 'constraint', 2_000),
    ),
    non_goals: (params.non_goals ?? []).map((item) =>
      clean(item, 'non-goal', 2_000),
    ),
    created_at: createdAt,
  }
}

function activeGoalId(options: GoalToolOptions, requested?: string): string {
  const id = requested?.trim() || options.getActiveGoal()
  if (!id) throw new Error('no active goal; call action=begin first')
  return id
}

export function goalTool(options: GoalToolOptions) {
  return defineTool({
    name: GOAL_TOOL_NAME,
    label: GOAL_TOOL_NAME,
    description:
      'Register and close a user goal. Call action=begin before non-trivial work, update it when scope changes, and complete it only after verification. Completing a goal queues a read-only background review; it does not block the answer.',
    promptGuidelines: [
      'Before non-trivial work, call `goal` with action="begin": parse the user request into 1-5 verifiable requirements, acceptance evidence, constraints, and non-goals. Do not use a goal for trivial conversation or a one-line status read.',
      'When the request changes, call action="update". Do not silently widen or replace the goal. If the user cancels or replaces the task, call action="cancel".',
      'Call action="complete" only when the requirements and acceptance checks are actually satisfied, with a short summary, verification commands, and residual risks. Completion queues a background review; do not wait for it or call review_task for the same goal.',
    ],
    parameters: goalParameters,
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
        const goal = normalizeGoal(params, id, now)
        options.appendEntry({ action: 'begin', goal_id: id, goal, at: now })
        options.setActiveGoal(id)
        return {
          content: [{ type: 'text', text: JSON.stringify({ action: 'begin', goal }) }],
          details: { action: 'begin', goal },
        }
      }

      if (params.action === 'update') {
        const id = activeGoalId(options, params.id)
        const state = goalStateFromBranch(branch, id)
        if (!state) throw new Error(`goal not found: ${id}`)
        const update = normalizeGoal(
          {
            title: params.title ?? state.goal.title,
            objective: params.objective ?? state.goal.objective,
            requirements: params.requirements ?? state.goal.requirements,
            acceptance: params.acceptance ?? state.goal.acceptance,
            constraints: params.constraints ?? state.goal.constraints,
            non_goals: params.non_goals ?? state.goal.non_goals,
          },
          id,
          state.goal.created_at,
        )
        options.appendEntry({ action: 'update', goal_id: id, goal: update, at: now })
        return {
          content: [{ type: 'text', text: JSON.stringify({ action: 'update', goal: update }) }],
          details: { action: 'update', goal: update },
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
        options.setActiveGoal(undefined)
        return {
          content: [{ type: 'text', text: JSON.stringify({ action: 'cancel', goal_id: id }) }],
          details: { action: 'cancel', goal_id: id },
        }
      }

      const id = activeGoalId(options, params.id)
      const state = goalStateFromBranch(branch, id)
      if (!state) throw new Error(`goal not found: ${id}`)
      const summary = clean(params.summary ?? '', 'summary', 4_000)
      const verification = (params.verification ?? []).map((item) =>
        clean(item, 'verification', 1_000),
      )
      const risks = (params.risks ?? []).map((item) => clean(item, 'risk', 1_000))
      const completion = [
        `Summary: ${summary}`,
        verification.length > 0
          ? `Verification:\n${verification.map((item) => `- ${item}`).join('\n')}`
          : '',
        risks.length > 0
          ? `Residual risks:\n${risks.map((item) => `- ${item}`).join('\n')}`
          : '',
      ]
        .filter((line) => line !== '')
        .join('\n')
      const transcript = `${goalTranscript(state.goal, branch, state.startIndex)}\n\nCompletion:\n${completion}`
      options.appendEntry({
        action: 'complete',
        goal_id: id,
        summary,
        verification,
        risks,
        at: now,
      })
      await options.enqueueReview({ goalId: id, cwd: ctx.cwd, transcript })
      options.setActiveGoal(undefined)
      return {
        content: [
          {
            type: 'text',
            text: JSON.stringify({
              action: 'complete',
              goal_id: id,
              review_queued: true,
            }),
          },
        ],
        details: { action: 'complete', goal_id: id, review_queued: true },
      }
    },
  })
}

/** Rebuild the active goal after a resume or branch switch. */
export function activeGoalFromBranch(branch: readonly unknown[]): string | undefined {
  let active: string | undefined
  for (const entry of branch) {
    const custom = customGoal(entry)
    if (!custom) continue
    const action = text(custom.data.action)
    const id = text(custom.data.goal_id)
    if (!id) continue
    if (action === 'begin') active = id
    else if (action === 'complete' || action === 'cancel' || action === 'supersede') {
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
