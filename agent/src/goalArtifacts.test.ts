// @tested-functions writeGoalArtifact, goalArtifactDir, pruneAllGoalArtifacts, pruneOldGoalArtifacts
import assert from 'node:assert/strict'
import { existsSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, statSync, utimesSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import test from 'node:test'

import {
  goalArtifactDir,
  goalArtifactRoot,
  MAX_GOAL_DIRS,
  pruneAllGoalArtifacts,
  pruneOldGoalArtifacts,
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

test('the whole artifact store is pruned to the newest goals, protecting the active goal and clearing empty sessions', async (t) => {
  const previous = process.env.MBFORGE_GOAL_ARTIFACT_DIR
  const root = mkdtempSync(join(tmpdir(), 'mbforge-goal-retention-'))
  process.env.MBFORGE_GOAL_ARTIFACT_DIR = root
  t.after(() => {
    if (previous === undefined) delete process.env.MBFORGE_GOAL_ARTIFACT_DIR
    else process.env.MBFORGE_GOAL_ARTIFACT_DIR = previous
  })

  // The active goal is given the OLDEST mtime so retention must protect it explicitly.
  const active = { sessionId: 's-active', goalId: 'goal-active' }
  await writeGoalArtifact({ ...active, toolName: 'read', content: 'a' })
  utimesSync(goalArtifactDir(active.sessionId, active.goalId), new Date(0), new Date(0))

  const extra = MAX_GOAL_DIRS + 5
  for (let index = 0; index < extra; index += 1) {
    const sessionId = `s${index % 3}`
    const goalId = `g${index}`
    await writeGoalArtifact({ sessionId, goalId, toolName: 'read', content: 'x' })
    const when = new Date((index + 1) * 1_000)
    utimesSync(goalArtifactDir(sessionId, goalId), when, when)
  }
  mkdirSync(join(root, 's-empty'), { recursive: true })

  const removed = await pruneOldGoalArtifacts(active)

  assert.equal(removed, extra + 1 - MAX_GOAL_DIRS)
  assert.ok(existsSync(goalArtifactDir(active.sessionId, active.goalId)), 'active goal survives')
  assert.ok(existsSync(goalArtifactDir(`s${(extra - 1) % 3}`, `g${extra - 1}`)), 'newest goal survives')
  assert.equal(existsSync(goalArtifactDir('s0', 'g0')), false, 'oldest removable goal pruned')
  assert.equal(existsSync(join(root, 's-empty')), false, 'empty session directory cleared')

  let remaining = 0
  for (const session of readdirSync(root)) {
    for (const goal of readdirSync(join(root, session))) {
      if (statSync(join(root, session, goal)).isDirectory()) remaining += 1
    }
  }
  assert.equal(remaining, MAX_GOAL_DIRS, 'store bounded to the newest goals')
})
