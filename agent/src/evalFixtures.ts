import { readdir, stat, unlink } from 'node:fs/promises'
import { join, resolve } from 'node:path'

import { getAgentDir } from '@earendil-works/pi-coding-agent'

import {
  baselineExpectations,
  gradeTrajectory,
  type BehaviorViolation,
} from './behaviorEval.js'
import { atomicWrite, readJsonFile } from './localStore.js'
import { trajectoryFromBranch, type Trajectory } from './trajectory.js'

const MAX_FIXTURES = 100

/** Fixture directory: an env override, else the gitignored agent home. */
export function evalFixtureDir(): string {
  const override = process.env.MBFORGE_EVAL_EXPORT_DIR?.trim()
  return override ? resolve(override) : join(getAgentDir(), 'EVAL_FIXTURES')
}

function isTrajectory(value: unknown): value is Trajectory {
  if (typeof value !== 'object' || value === null || Array.isArray(value))
    return false
  const record = value as Record<string, unknown>
  return typeof record.goalId === 'string' && Array.isArray(record.steps)
}

async function pruneFixtures(directory: string): Promise<void> {
  const names = (await readdir(directory).catch(() => [])).filter((name) =>
    name.endsWith('.json'),
  )
  if (names.length <= MAX_FIXTURES) return
  const stats = await Promise.all(
    names.map(async (name) => ({
      name,
      mtime: (await stat(join(directory, name)).catch(() => ({ mtimeMs: 0 })))
        .mtimeMs,
    })),
  )
  stats.sort((left, right) => left.mtime - right.mtime)
  for (const { name } of stats.slice(0, stats.length - MAX_FIXTURES)) {
    await unlink(join(directory, name)).catch(() => {})
  }
}

/**
 * Freeze a completed goal's trajectory as a regression fixture. Default-on and
 * best-effort: a goal with no tool calls produces nothing, and a write failure
 * never blocks completion. Old fixtures are pruned so the store stays bounded.
 */
export async function exportGoalFixture(
  goalId: string,
  branch: readonly unknown[],
  mode?: string,
): Promise<void> {
  const trajectory = trajectoryFromBranch(branch, goalId)
  if (!trajectory) return
  const directory = evalFixtureDir()
  const safeId = goalId.replace(/[^a-zA-Z0-9_.-]/g, '_')
  await atomicWrite(
    join(directory, `${safeId}.json`),
    `${JSON.stringify({ ...trajectory, mode }, null, 2)}\n`,
  )
  await pruneFixtures(directory)
}

export interface FixtureResult {
  file: string
  violations: BehaviorViolation[]
}

/** Load every valid stored trajectory (the raw experience for skill induction). */
export async function loadFixtures(
  directory = evalFixtureDir(),
): Promise<Trajectory[]> {
  const names = (await readdir(directory).catch(() => []))
    .filter((name) => name.endsWith('.json'))
    .sort()
  const trajectories: Trajectory[] = []
  for (const name of names) {
    const raw = await readJsonFile(join(directory, name)).catch(() => undefined)
    if (isTrajectory(raw)) trajectories.push(raw)
  }
  return trajectories
}

/**
 * Grade every fixture against its auto-derived baseline; returns only the
 * fixtures that violate an invariant. An absent or empty directory yields [],
 * so the regression gate is a no-op until real runs accumulate.
 */
export async function sweepFixtures(
  directory = evalFixtureDir(),
): Promise<FixtureResult[]> {
  const names = (await readdir(directory).catch(() => []))
    .filter((name) => name.endsWith('.json'))
    .sort()
  const results: FixtureResult[] = []
  for (const name of names) {
    const raw = await readJsonFile(join(directory, name)).catch(() => undefined)
    if (!isTrajectory(raw)) continue
    const report = gradeTrajectory(raw, baselineExpectations(raw))
    if (report.violations.length > 0) {
      results.push({ file: name, violations: report.violations })
    }
  }
  return results
}
