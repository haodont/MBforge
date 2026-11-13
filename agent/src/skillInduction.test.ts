// @tested-functions pruneSkeleton, induceSkills, refreshSkills, recordSuccess, learnedMethodsPrompt
import assert from 'node:assert/strict'
import { mkdtempSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import test from 'node:test'

import {
  ACTIVE_SUCCESSES,
  induceSkills,
  learnedMethodsPrompt,
  pruneSkeleton,
  readSkills,
  recordSuccess,
  refreshSkills,
} from './skillInduction.js'
import type { Trajectory, TrajectoryStep } from './trajectory.js'

function step(tool: string, status: 'ok' | 'error' = 'ok'): TrajectoryStep {
  return { tool, inputDigest: 'd', status, at: '' }
}

function fixture(goalId: string, steps: TrajectoryStep[]): Trajectory {
  return { goalId, title: goalId, steps }
}

test('skills are pruned methods induced by multi-goal recurrence and activated by observed success', async (t) => {
  const previousSkills = process.env.MBFORGE_SKILLS_FILE
  const previousFixtures = process.env.MBFORGE_EVAL_EXPORT_DIR
  const skillsDir = mkdtempSync(join(tmpdir(), 'mbforge-skills-'))
  const fixtureDir = mkdtempSync(join(tmpdir(), 'mbforge-skill-fixtures-'))
  process.env.MBFORGE_SKILLS_FILE = join(skillsDir, 'SKILLS.json')
  process.env.MBFORGE_EVAL_EXPORT_DIR = fixtureDir
  t.after(() => {
    if (previousSkills === undefined) delete process.env.MBFORGE_SKILLS_FILE
    else process.env.MBFORGE_SKILLS_FILE = previousSkills
    if (previousFixtures === undefined)
      delete process.env.MBFORGE_EVAL_EXPORT_DIR
    else process.env.MBFORGE_EVAL_EXPORT_DIR = previousFixtures
  })

  // Prune collapses consecutive repeats and drops recovered dead-ends.
  const pruned = pruneSkeleton([
    step('search'),
    step('search'),
    step('analyze'),
    step('bash', 'error'),
    step('report'),
  ])
  assert.deepEqual(pruned, ['search', 'analyze', 'report'])

  const method = [step('search'), step('analyze'), step('report')]
  const fixtures = [
    fixture('goal-1', [
      step('search'),
      step('search'),
      step('analyze'),
      step('bash', 'error'),
      step('report'),
    ]),
    fixture('goal-2', method),
    fixture('goal-3', [step('read'), step('write')]), // one-off: not a method
  ]
  writeFileSync(join(fixtureDir, 'goal-1.json'), JSON.stringify(fixtures[0]))
  writeFileSync(join(fixtureDir, 'goal-2.json'), JSON.stringify(fixtures[1]))
  writeFileSync(join(fixtureDir, 'goal-3.json'), JSON.stringify(fixtures[2]))

  // Recurrence across two distinct goals yields one candidate; the one-off is excluded.
  const induced = induceSkills(fixtures)
  assert.equal(induced.length, 1)
  assert.deepEqual(induced[0].steps, ['search', 'analyze', 'report'])
  assert.equal(induced[0].occurrences, 2)
  assert.equal(induced[0].status, 'candidate')

  const refreshed = await refreshSkills()
  assert.equal(refreshed.length, 1)

  // Confidence ladder: success credits activate the candidate.
  for (let index = 0; index < ACTIVE_SUCCESSES; index += 1) {
    await recordSuccess(['search', 'analyze', 'report'])
  }
  const stored = await readSkills()
  assert.equal(stored[0].successes, ACTIVE_SUCCESSES)
  assert.equal(stored[0].status, 'active')

  const prompt = learnedMethodsPrompt(stored)
  assert.match(prompt, /## Learned methods/)
  assert.match(prompt, /search → analyze → report/)
  assert.equal(
    learnedMethodsPrompt(induced),
    '',
    'candidates are not injected until active',
  )
})
