import { createHash } from 'node:crypto'
import { join, resolve } from 'node:path'

import { getAgentDir } from '@earendil-works/pi-coding-agent'

import { loadFixtures } from './evalFixtures.js'
import { atomicWrite, readJsonFile } from './localStore.js'
import type { Trajectory, TrajectoryStep } from './trajectory.js'

/** A learned method: a pruned tool skeleton that recurred across distinct goals. */
export interface LearnedSkill {
  id: string
  steps: string[]
  trigger: string
  occurrences: number
  successes: number
  status: 'candidate' | 'active'
}

/** Recurrence across distinct goals required to become a candidate. */
export const MIN_OCCURRENCES = 2
/** Successful completions following a candidate required to activate it. */
export const ACTIVE_SUCCESSES = 2
const MAX_SKILLS = 50

export function skillStorePath(): string {
  const override = process.env.MBFORGE_SKILLS_FILE?.trim()
  return override ? resolve(override) : join(getAgentDir(), 'SKILLS.json')
}

export async function readSkills(): Promise<LearnedSkill[]> {
  const raw = await readJsonFile(skillStorePath()).catch(() => undefined)
  if (!Array.isArray(raw)) return []
  return raw.filter(isSkill)
}

function isSkill(value: unknown): value is LearnedSkill {
  if (typeof value !== 'object' || value === null) return false
  const record = value as Record<string, unknown>
  return (
    typeof record.id === 'string' &&
    Array.isArray(record.steps) &&
    typeof record.occurrences === 'number' &&
    typeof record.successes === 'number' &&
    (record.status === 'candidate' || record.status === 'active')
  )
}

async function writeSkills(skills: LearnedSkill[]): Promise<void> {
  await atomicWrite(skillStorePath(), `${JSON.stringify(skills, null, 2)}\n`)
}

/**
 * Prune a trajectory to its minimal sufficient tool skeleton: drop failed
 * attempts (dead ends that were recovered from) and collapse consecutive
 * repeats (the no-progress loop signal). Instance values never enter the
 * skeleton, so what remains is the transferable method, not a task replay.
 */
export function pruneSkeleton(steps: readonly TrajectoryStep[]): string[] {
  const skeleton: string[] = []
  for (const step of steps) {
    if (step.status === 'error') continue
    if (skeleton[skeleton.length - 1] === step.tool) continue
    skeleton.push(step.tool)
  }
  return skeleton
}

export function skeletonKey(steps: readonly string[]): string {
  return steps.join('>')
}

function skillId(key: string): string {
  return `skill-${createHash('sha256').update(key).digest('hex').slice(0, 8)}`
}

/**
 * Induce candidate methods by recurrence: a pruned skeleton seen in at least
 * MIN_OCCURRENCES distinct goals is a transferable method, not a one-off.
 * Existing successes/status are preserved so the confidence ladder survives
 * re-induction. Compression gain is approximated by recurrence count.
 */
export function induceSkills(
  fixtures: readonly Trajectory[],
  existing: readonly LearnedSkill[] = [],
): LearnedSkill[] {
  const byKey = new Map<string, { steps: string[]; goals: Set<string> }>()
  for (const fixture of fixtures) {
    const steps = pruneSkeleton(fixture.steps)
    if (steps.length === 0) continue
    const key = skeletonKey(steps)
    const entry = byKey.get(key) ?? { steps, goals: new Set<string>() }
    entry.goals.add(fixture.goalId)
    byKey.set(key, entry)
  }
  const prior = new Map(existing.map((skill) => [skill.id, skill]))
  const skills: LearnedSkill[] = []
  for (const [key, entry] of byKey) {
    if (entry.goals.size < MIN_OCCURRENCES) continue
    const id = skillId(key)
    const before = prior.get(id)
    const successes = before?.successes ?? 0
    skills.push({
      id,
      steps: entry.steps,
      trigger: `recurring method: ${entry.steps.join(' → ')}`,
      occurrences: entry.goals.size,
      successes,
      status: successes >= ACTIVE_SUCCESSES ? 'active' : 'candidate',
    })
  }
  skills.sort((left, right) => right.occurrences - left.occurrences)
  return skills.slice(0, MAX_SKILLS)
}

/** Re-induce from the stored fixtures and persist the merged skill set. */
export async function refreshSkills(): Promise<LearnedSkill[]> {
  const [fixtures, existing] = await Promise.all([loadFixtures(), readSkills()])
  const skills = induceSkills(fixtures, existing)
  await writeSkills(skills)
  return skills
}

/** Credit a completed goal whose skeleton matches a skill; promote on success. */
export async function recordSuccess(steps: readonly string[]): Promise<void> {
  const key = skeletonKey(steps)
  const skills = await readSkills()
  let changed = false
  for (const skill of skills) {
    if (skeletonKey(skill.steps) !== key) continue
    skill.successes += 1
    if (skill.successes >= ACTIVE_SUCCESSES) skill.status = 'active'
    changed = true
  }
  if (changed) await writeSkills(skills)
}

/** Compact prompt section listing activated learned methods (empty when none). */
export function learnedMethodsPrompt(skills: readonly LearnedSkill[]): string {
  const active = skills.filter((skill) => skill.status === 'active')
  if (active.length === 0) return ''
  return [
    '## Learned methods',
    'Tool sequences that repeatedly succeeded on similar past goals. Prefer them when they fit; they are advice, not instructions.',
    ...active.map((skill) => `- ${skill.steps.join(' → ')}`),
  ].join('\n')
}
