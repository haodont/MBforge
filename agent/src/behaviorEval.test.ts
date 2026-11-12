// @tested-functions trajectoryFromBranch, exportTrajectoryFile, gradeTrajectory, detectNoProgress
import assert from 'node:assert/strict'
import { mkdtemp, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import test from 'node:test'

import {
  DEFAULT_REPEAT_THRESHOLD,
  detectNoProgress,
  gradeTrajectory,
} from './behaviorEval.js'
import { GOAL_ENTRY_TYPE } from './goal.js'
import { readJsonFile } from './localStore.js'
import {
  exportTrajectoryFile,
  trajectoryFromBranch,
  type Trajectory,
} from './trajectory.js'

function toolEntry(
  goalId: string,
  tool: string,
  inputDigest: string,
  status: 'ok' | 'error' = 'ok',
) {
  return {
    type: 'custom',
    customType: GOAL_ENTRY_TYPE,
    data: { action: 'tool', goal_id: goalId, tool, input_digest: inputDigest, status },
  }
}

test('a real-run trajectory freezes to a fixture and the behavioral gate catches loops, forbidden tools, and budget overruns', async () => {
  const branch: unknown[] = [
    {
      type: 'custom',
      customType: GOAL_ENTRY_TYPE,
      data: {
        action: 'begin',
        goal_id: 'goal-eval',
        goal: { id: 'goal-eval', title: 'Compare activities', objective: 'x' },
      },
    },
    toolEntry('goal-eval', 'resolve_document', 'd1'),
    toolEntry('goal-eval', 'search_evidence', 'd2'),
    toolEntry('goal-eval', 'search_evidence', 'd2'),
    toolEntry('goal-eval', 'search_evidence', 'd2'),
    toolEntry('goal-eval', 'get_patent_result', 'd3'),
    toolEntry('goal-eval', 'bash', 'd4'),
    toolEntry('goal-other', 'search_evidence', 'd9'),
  ]

  const trajectory = trajectoryFromBranch(branch)
  assert.ok(trajectory)
  assert.equal(trajectory.goalId, 'goal-eval')
  assert.equal(trajectory.title, 'Compare activities')
  assert.equal(trajectory.steps.length, 6)
  assert.deepEqual(
    trajectory.steps.map((step) => step.tool),
    ['resolve_document', 'search_evidence', 'search_evidence', 'search_evidence', 'get_patent_result', 'bash'],
  )
  assert.equal(trajectoryFromBranch(branch, 'goal-missing'), undefined)
  assert.equal(trajectoryFromBranch([{ type: 'message' }]), undefined)

  const directory = await mkdtemp(join(tmpdir(), 'mbforge-eval-'))
  try {
    const path = join(directory, 'fixture.json')
    await exportTrajectoryFile(path, trajectory)
    assert.deepEqual((await readJsonFile(path)) as Trajectory, trajectory)
  } finally {
    await rm(directory, { recursive: true, force: true })
  }

  const loop = detectNoProgress(trajectory.steps, DEFAULT_REPEAT_THRESHOLD)
  assert.deepEqual(loop, { tool: 'search_evidence', inputDigest: 'd2', count: 3 })

  const report = gradeTrajectory(trajectory, {
    requiredTools: ['resolve_document', 'search_evidence'],
    forbiddenTools: ['bash'],
    maxSteps: 5,
    maxConsecutiveRepeats: 3,
  })
  assert.equal(report.passed, false)
  assert.equal(report.stepCount, 6)
  const rules = report.violations.map((violation) => violation.rule).sort()
  assert.deepEqual(rules, ['forbidden_tool', 'no_progress', 'step_budget'])

  const clean: Trajectory = {
    ...trajectory,
    steps: [
      trajectory.steps[0],
      trajectory.steps[1],
      trajectory.steps[4],
    ],
  }
  const cleanReport = gradeTrajectory(clean, {
    requiredTools: ['resolve_document', 'search_evidence'],
    forbiddenTools: ['bash'],
    maxSteps: 5,
  })
  assert.equal(cleanReport.passed, true)
  assert.deepEqual(cleanReport.violations, [])
  assert.equal(detectNoProgress(clean.steps), undefined)
})