// @tested-functions writeGoalArtifact, goalArtifactDir, pruneAllGoalArtifacts
import assert from 'node:assert/strict'
import { mkdtempSync, readFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import test from 'node:test'

import {
  goalArtifactDir,
  goalArtifactRoot,
  pruneAllGoalArtifacts,
  writeGoalArtifact,
} from './goalArtifacts.js'

test('goal artifacts are bounded and scoped to session and goal', async (t) => {
  const previous = process.env.MBFORGE_GOAL_ARTIFACT_DIR
  const root = mkdtempSync(join(tmpdir(), 'mbforge-goal-artifacts-'))
  process.env.MBFORGE_GOAL_ARTIFACT_DIR = root
  t.after(() => {
    if (previous === undefined) delete process.env.MBFORGE_GOAL_ARTIFACT_DIR
    else process.env.MBFORGE_GOAL_ARTIFACT_DIR = previous
  })

  assert.equal(goalArtifactRoot(), root)
  const path = await writeGoalArtifact({
    sessionId: 'session/1',
    goalId: 'goal-1',
    toolName: 'bash',
    content: 'x'.repeat(250_000),
  })
  assert.match(path, /session_1[\\/]goal-1[\\/].*bash\.txt$/)
  assert.equal(readFileSync(path, 'utf8').length, 200_001)
  assert.equal(goalArtifactDir('session/1', 'goal-1'), join(root, 'session_1', 'goal-1'))

  const removed = await pruneAllGoalArtifacts()
  assert.equal(removed, 0)
})
