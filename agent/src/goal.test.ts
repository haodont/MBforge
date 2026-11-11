// @tested-functions goalTool, activeGoalFromBranch, goalStateFromBranch
import assert from 'node:assert/strict'
import test from 'node:test'

import {
  activeGoalFromBranch,
  GOAL_ENTRY_TYPE,
  goalStateFromBranch,
  goalTool,
  goalTranscript,
  type GoalReviewJob,
} from './goal.js'

function fakeContext(branch: unknown[]) {
  return {
    cwd: 'C:/repo',
    sessionManager: { getBranch: () => branch },
  } as never
}

test('goal lifecycle records a goal and queues a scoped review on completion', async () => {
  const branch: unknown[] = []
  const queued: GoalReviewJob[] = []
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

  branch.push({
    type: 'message',
    message: { role: 'user', content: 'Please keep the API stable.' },
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
})

test('goal transcript includes the tool artifact index', () => {
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
          acceptance: [],
          constraints: [],
          non_goals: [],
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
