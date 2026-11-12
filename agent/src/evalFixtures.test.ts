// @tested-functions exportGoalFixture, sweepFixtures, baselineExpectations
import assert from 'node:assert/strict'
import { mkdtemp, readdir, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import test from 'node:test'

import { exportGoalFixture, sweepFixtures } from './evalFixtures.js'
import { GOAL_ENTRY_TYPE } from './goal.js'

function branchWith(goalId: string, tools: Array<[string, string]>): unknown[] {
  const branch: unknown[] = [
    {
      type: 'custom',
      customType: GOAL_ENTRY_TYPE,
      data: { action: 'begin', goal_id: goalId, goal: { id: goalId, title: goalId, objective: 'x' } },
    },
  ]
  for (const [tool, digest] of tools) {
    branch.push({
      type: 'custom',
      customType: GOAL_ENTRY_TYPE,
      data: { action: 'tool', goal_id: goalId, tool, input_digest: digest, status: 'ok' },
    })
  }
  return branch
}

test('completed goals auto-export fixtures and the sweep flags loops and capability bypass, bounded', async (t) => {
  const directory = await mkdtemp(join(tmpdir(), 'mbforge-eval-fix-'))
  const previous = process.env.MBFORGE_EVAL_EXPORT_DIR
  process.env.MBFORGE_EVAL_EXPORT_DIR = directory
  t.after(async () => {
    if (previous === undefined) delete process.env.MBFORGE_EVAL_EXPORT_DIR
    else process.env.MBFORGE_EVAL_EXPORT_DIR = previous
    await rm(directory, { recursive: true, force: true })
  })

  await exportGoalFixture(
    'goal-clean',
    branchWith('goal-clean', [['resolve_document', 'd1'], ['search_evidence', 'd2']]),
    'auto',
  )
  await exportGoalFixture(
    'goal-bad',
    branchWith('goal-bad', [
      ['search_evidence', 'd2'],
      ['search_evidence', 'd2'],
      ['search_evidence', 'd2'],
      ['bash', 'd4'],
    ]),
    'auto',
  )

  const results = await sweepFixtures(directory)
  assert.equal(results.length, 1)
  assert.equal(results[0]?.file, 'goal-bad.json')
  assert.deepEqual(
    (results[0]?.violations ?? []).map((violation) => violation.rule).sort(),
    ['forbidden_tool', 'no_progress'],
  )

  // In dev mode the repo tools are legitimate, so the same bash call is not a bypass.
  await exportGoalFixture('goal-dev', branchWith('goal-dev', [['bash', 'd4']]), 'dev')
  const devResults = await sweepFixtures(directory)
  assert.equal(devResults.some((result) => result.file === 'goal-dev.json'), false)

  for (let index = 0; index < 105; index += 1) {
    await exportGoalFixture(
      `goal-bulk-${index}`,
      branchWith(`goal-bulk-${index}`, [['search_evidence', `d${index}`]]),
      'auto',
    )
  }
  const names = (await readdir(directory)).filter((name) => name.endsWith('.json'))
  assert.ok(names.length <= 100, `fixture store must stay bounded, got ${names.length}`)
})

test('the built-in regression sweep passes on the active fixture store', async () => {
  const results = await sweepFixtures()
  assert.deepEqual(results, [], `behavioral regressions detected: ${JSON.stringify(results)}`)
})