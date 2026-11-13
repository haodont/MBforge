// @tested-functions goalTool, activeGoalFromBranch, goalStateFromBranch, goalContractPrompt
import assert from 'node:assert/strict'
import test from 'node:test'

import {
  activeGoalFromBranch,
  GOAL_ENTRY_TYPE,
  goalContractPrompt,
  goalStateFromBranch,
  goalTool,
  goalTranscript,
  type GoalReviewJob,
} from './goal.js'
import { trajectoryFromBranch } from './trajectory.js'

function fakeContext(branch: unknown[]) {
  return {
    cwd: 'C:/repo',
    sessionManager: { getBranch: () => branch },
  } as never
}

function harness(branch: unknown[]) {
  const queued: GoalReviewJob[] = []
  const archived: Array<{ goalId: string; branch: readonly unknown[] }> = []
  let active: string | undefined
  const tool = goalTool({
    appendEntry: (data) => {
      branch.push({ type: 'custom', customType: GOAL_ENTRY_TYPE, data })
    },
    enqueueReview: (job) => {
      queued.push(job)
    },
    getActiveGoal: () => active,
    setActiveGoal: (id) => {
      active = id
    },
    archiveTrajectory: (goalId, recorded) => {
      archived.push({ goalId, branch: recorded })
    },
  })
  const run = (params: Record<string, unknown>) =>
    tool.execute(params.action as string, params, undefined, undefined, fakeContext(branch))
  return { run, queued, archived, activeId: () => active }
}

test('goal is a living plan: light begin, progress with evidence, pause/resume, complete reports unmet', async () => {
  const branch: unknown[] = []
  const { run, queued, archived, activeId } = harness(branch)

  const started = await run({
    action: 'begin',
    objective: 'Make review counts refresh after a decision.',
  })
  const goalId = activeId()
  assert.ok(goalId)
  assert.match(JSON.stringify(started.details), /goal-/)
  assert.equal(started.details.goal.requirements.length, 0, 'begin needs only an objective')
  assert.equal(started.details.goal.title, 'Make review counts refresh after a decision.')

  const added = await run({
    action: 'progress',
    requirements: [{ text: 'Invalidate the review query' }, { text: 'Add a focused test' }],
  })
  assert.equal(added.details.total, 2)

  const marked = await run({
    action: 'progress',
    requirements: [
      { id: 'r1', status: 'done', evidence: 'ev-7' },
      { id: 'r2', status: 'blocked', note: 'waiting on a decision' },
    ],
  })
  assert.equal(marked.details.done, 1)

  branch.push({
    type: 'custom',
    customType: GOAL_ENTRY_TYPE,
    data: { action: 'tool', goal_id: goalId, tool: 'search_evidence', input_digest: 'd1', status: 'ok' },
  })

  const paused = await run({ action: 'update', status: 'paused' })
  assert.equal(paused.details.goal.status, 'paused')
  assert.equal(activeId(), goalId, 'a paused goal keeps its slot')
  const contract = goalContractPrompt(goalStateFromBranch(branch, goalId!)!.goal)
  assert.match(contract, /\(paused\)/)
  assert.match(contract, /1\/2 done/)
  assert.match(contract, /\[done\] r1: Invalidate the review query \(evidence: ev-7\)/)
  assert.match(contract, /\[blocked\] r2: Add a focused test — waiting on a decision/)

  await run({ action: 'update', status: 'active' })
  assert.equal(goalStateFromBranch(branch, goalId!)!.goal.status, 'active')

  const completed = await run({ action: 'complete' })
  assert.equal(activeId(), undefined)
  assert.equal(activeGoalFromBranch(branch), undefined)
  assert.deepEqual(
    completed.details.unmet.map((item: { id: string }) => item.id),
    ['r2'],
    'complete surfaces the unmet requirement instead of blocking',
  )
  assert.equal(queued.length, 1)
  assert.match(queued[0]?.transcript ?? '', /\[done\] r1/)
  assert.match(queued[0]?.transcript ?? '', /\[blocked\] r2/)
  assert.equal(archived.length, 1)
  const frozen = trajectoryFromBranch(archived[0]?.branch ?? [], goalId!)
  assert.equal(frozen?.steps.length, 1)
  assert.equal(frozen?.steps[0]?.tool, 'search_evidence')
})

test('goal transcript and contract prompt render the definition and tool index', () => {
  const branch: unknown[] = [
    {
      type: 'custom',
      customType: GOAL_ENTRY_TYPE,
      data: {
        action: 'begin',
        goal_id: 'goal-tools',
        goal: {
          id: 'goal-tools',
          title: 'Inspect page',
          objective: 'Check one page.',
          requirements: [{ id: 'r1', text: 'Read it', status: 'done', evidence: 'ev-1' }],
          constraints: ['Keep the API stable'],
          non_goals: ['No rewrite'],
          status: 'active',
          created_at: '2026-01-01T00:00:00.000Z',
        },
      },
    },
    {
      type: 'custom',
      customType: GOAL_ENTRY_TYPE,
      data: {
        action: 'tool',
        goal_id: 'goal-tools',
        tool: 'inspect_visual',
        input: '{"page":1}',
        input_digest: 'abc123',
        status: 'ok',
      },
    },
  ]
  const state = goalStateFromBranch(branch, 'goal-tools')
  assert.ok(state)
  const transcript = goalTranscript(state.goal, branch, state.startIndex)
  assert.match(transcript, /Tool index/)
  assert.match(transcript, /inspect_visual ok input=\{"page":1\}/)

  const contract = goalContractPrompt(state.goal)
  assert.match(contract, /## Active goal contract/)
  assert.match(contract, /1\/1 done/)
  assert.match(contract, /\[done\] r1: Read it \(evidence: ev-1\)/)
  assert.match(contract, /Constraints:\n- Keep the API stable/)
  assert.match(contract, /Non-goals:\n- No rewrite/)
  assert.match(contract, /action=progress/)
})

test('goal state survives the branch: legacy string requirements, progress merge, and pause', () => {
  const branch: unknown[] = [
    {
      type: 'custom',
      customType: GOAL_ENTRY_TYPE,
      data: {
        action: 'begin',
        goal_id: 'goal-1234',
        goal: {
          id: 'goal-1234',
          title: 'Keep the branch',
          objective: 'Resume the goal.',
          requirements: ['One requirement'],
          created_at: '2026-01-01T00:00:00.000Z',
        },
      },
    },
  ]
  assert.equal(activeGoalFromBranch(branch), 'goal-1234')
  assert.deepEqual(goalStateFromBranch(branch, 'goal-1234')?.goal.requirements, [
    { id: 'r1', text: 'One requirement', status: 'pending' },
  ])

  branch.push({
    type: 'custom',
    customType: GOAL_ENTRY_TYPE,
    data: {
      action: 'progress',
      goal_id: 'goal-1234',
      requirements: [{ id: 'r1', text: 'One requirement', status: 'done', evidence: 'ev-9' }],
    },
  })
  branch.push({
    type: 'custom',
    customType: GOAL_ENTRY_TYPE,
    data: {
      action: 'update',
      goal_id: 'goal-1234',
      goal: {
        id: 'goal-1234',
        title: 'Keep the branch',
        objective: 'Resume the goal.',
        requirements: [{ id: 'r1', text: 'One requirement', status: 'done', evidence: 'ev-9' }],
        constraints: [],
        non_goals: [],
        status: 'paused',
        created_at: '2026-01-01T00:00:00.000Z',
      },
    },
  })
  const state = goalStateFromBranch(branch, 'goal-1234')
  assert.equal(state?.goal.status, 'paused')
  assert.equal(state?.goal.requirements[0]?.status, 'done')
  assert.equal(activeGoalFromBranch(branch), 'goal-1234', 'paused goal stays active')

  branch.push({
    type: 'custom',
    customType: GOAL_ENTRY_TYPE,
    data: { action: 'cancel', goal_id: 'goal-1234', at: '2026-01-01T00:01:00.000Z' },
  })
  assert.equal(activeGoalFromBranch(branch), undefined)
})
