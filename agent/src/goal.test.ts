// @tested-functions goalTool, activeGoalFromBranch, goalStateFromBranch
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

test('goal lifecycle records a goal, queues a scoped review, and archives the trajectory on completion', async () => {
  const branch: unknown[] = []
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

  const started = await tool.execute(
    'begin',
    {
      action: 'begin',
      title: 'Fix review cache',
      objective: 'Make review counts refresh after a decision.',
      requirements: ['Invalidate the review query after a decision'],
      acceptance: ['Focused frontend test passes'],
    },
    undefined,
    undefined,
    fakeContext(branch),
  )
  assert.match(JSON.stringify(started.details), /goal-/)
  assert.ok(active)
  const goalId = active

  branch.push({
    type: 'message',
    message: { role: 'user', content: 'Please keep the API stable.' },
  })
  branch.push({
    type: 'custom',
    customType: GOAL_ENTRY_TYPE,
    data: {
      action: 'tool',
      goal_id: goalId,
      tool: 'search_evidence',
      input_digest: 'd1',
      status: 'ok',
    },
  })

  await tool.execute(
    'complete',
    {
      action: 'complete',
      summary: 'The review query is invalidated after a decision.',
      verification: ['npm run test -> passed'],
      risks: ['None.'],
    },
    undefined,
    undefined,
    fakeContext(branch),
  )

  assert.equal(active, undefined)
  assert.equal(activeGoalFromBranch(branch), undefined)
  assert.equal(queued.length, 1)
  assert.match(queued[0]?.transcript ?? '', /Fix review cache/)
  assert.match(queued[0]?.transcript ?? '', /Please keep the API stable/)
  assert.match(queued[0]?.transcript ?? '', /The review query is invalidated/)
  assert.match(queued[0]?.transcript ?? '', /npm run test -> passed/)

  assert.equal(archived.length, 1)
  assert.equal(archived[0]?.goalId, goalId)
  const frozen = trajectoryFromBranch(archived[0]?.branch ?? [], goalId)
  assert.equal(frozen?.steps.length, 1)
  assert.equal(frozen?.steps[0]?.tool, 'search_evidence')
})

test('goal mirrors the active objective into the durable ledger across its lifecycle', async () => {
  const branch: unknown[] = []
  let active: string | undefined
  const mirrored: Array<{ id: string; title: string } | null> = []
  const tool = goalTool({
    appendEntry: (data) => {
      branch.push({ type: 'custom', customType: GOAL_ENTRY_TYPE, data })
    },
    enqueueReview: () => {},
    getActiveGoal: () => active,
    setActiveGoal: (id) => {
      active = id
    },
    persistActive: (goal) => {
      mirrored.push(goal ? { id: goal.id, title: goal.title } : null)
    },
  })

  await tool.execute(
    'begin',
    { action: 'begin', title: 'Design candidates', objective: 'Propose candidates.', requirements: ['r1'] },
    undefined,
    undefined,
    fakeContext(branch),
  )
  assert.equal(mirrored.length, 1)
  assert.equal(mirrored[0]?.title, 'Design candidates')

  await tool.execute(
    'update',
    { action: 'update', title: 'Design candidates v2' },
    undefined,
    undefined,
    fakeContext(branch),
  )
  assert.equal(mirrored.length, 2)
  assert.equal(mirrored[1]?.title, 'Design candidates v2', 'update mirrors the revised objective')

  await tool.execute(
    'complete',
    { action: 'complete', summary: 'done' },
    undefined,
    undefined,
    fakeContext(branch),
  )
  assert.equal(mirrored.length, 3)
  assert.equal(mirrored[2], null, 'completion clears the mirrored goal')
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
          requirements: ['Read it'],
          acceptance: ['It is read'],
          constraints: ['Keep the API stable'],
          non_goals: ['No rewrite'],
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
        artifact: 'C:/agent/GOAL_ARTIFACTS/s/g/1.txt',
      },
    },
  ]
  const state = goalStateFromBranch(branch, 'goal-tools')
  assert.ok(state)
  const transcript = goalTranscript(state.goal, branch, state.startIndex)
  assert.match(transcript, /Tool index/)
  assert.match(transcript, /inspect_visual ok input=\{"page":1\}/)
  assert.match(transcript, /GOAL_ARTIFACTS/)

  const contract = goalContractPrompt(state.goal)
  assert.match(contract, /## Active goal contract/)
  assert.match(contract, /Acceptance:\n- It is read/)
  assert.match(contract, /Constraints:\n- Keep the API stable/)
  assert.match(contract, /Non-goals:\n- No rewrite/)
  assert.match(contract, /do not call goal complete until they are satisfied/)
})

test('goal state and active flag survive from the branch', () => {
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
          acceptance: [],
          constraints: [],
          non_goals: [],
          created_at: '2026-01-01T00:00:00.000Z',
        },
      },
    },
  ]
  assert.equal(activeGoalFromBranch(branch), 'goal-1234')
  assert.deepEqual(
    goalStateFromBranch(branch, 'goal-1234')?.goal.requirements,
    ['One requirement'],
  )
  branch.push({
    type: 'custom',
    customType: GOAL_ENTRY_TYPE,
    data: { action: 'cancel', goal_id: 'goal-1234', at: '2026-01-01T00:01:00.000Z' },
  })
  assert.equal(activeGoalFromBranch(branch), undefined)
})
