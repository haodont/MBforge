import { randomUUID } from 'node:crypto'
import { existsSync } from 'node:fs'
import { mkdir, readdir, stat, unlink, writeFile } from 'node:fs/promises'
import { join, resolve } from 'node:path'

import { getAgentDir } from '@earendil-works/pi-coding-agent'

const MAX_FILES_PER_GOAL = 200
const MAX_BYTES_PER_GOAL = 50 * 1024 * 1024
const MAX_ARTIFACT_BYTES = 200_000

function safe(value: string): string {
  return value.replace(/[^a-zA-Z0-9_.-]/g, '_')
}

export function goalArtifactRoot(): string {
  const override = process.env.MBFORGE_GOAL_ARTIFACT_DIR?.trim()
  return override ? resolve(override) : join(getAgentDir(), 'GOAL_ARTIFACTS')
}

export function goalArtifactDir(sessionId: string, goalId: string): string {
  return join(goalArtifactRoot(), safe(sessionId), safe(goalId))
}

export interface GoalArtifactInput {
  sessionId: string
  goalId: string
  toolName: string
  content: string
}

async function pruneDirectory(directory: string): Promise<void> {
  const names = await readdir(directory).catch(() => [])
  if (names.length === 0) return
  const files: Array<{ path: string; size: number; mtime: number }> = []
  for (const name of names) {
    const path = join(directory, name)
    try {
      const info = await stat(path)
      if (!info.isFile()) continue
      files.push({ path, size: info.size, mtime: info.mtimeMs })
    } catch {
      // A file can disappear between readdir and stat; ignore it.
    }
  }
  let total = files.reduce((sum, file) => sum + file.size, 0)
  files.sort((left, right) => left.mtime - right.mtime)
  while (files.length > MAX_FILES_PER_GOAL || total > MAX_BYTES_PER_GOAL) {
    const file = files.shift()
    if (!file) break
    try {
      await unlink(file.path)
      total -= file.size
    } catch {
      // Best effort; a failed prune must not fail the tool result.
    }
  }
}

/** Write a bounded tool output and prune the oldest artifacts for this goal. */
export async function writeGoalArtifact(input: GoalArtifactInput): Promise<string> {
  const directory = goalArtifactDir(input.sessionId, input.goalId)
  await mkdir(directory, { recursive: true, mode: 0o700 })
  const path = join(
    directory,
    `${Date.now()}-${randomUUID().slice(0, 8)}-${safe(input.toolName)}.txt`,
  )
  const body = input.content.slice(0, MAX_ARTIFACT_BYTES)
  await writeFile(path, `${body}\n`, { encoding: 'utf8', mode: 0o600 })
  await pruneDirectory(directory)
  return path
}

/** Remove old artifact directories; used by maintenance commands, not tool calls. */
export async function pruneAllGoalArtifacts(): Promise<number> {
  const root = goalArtifactRoot()
  if (!existsSync(root)) return 0
  let removed = 0
  const sessions = await readdir(root).catch(() => [])
  for (const session of sessions) {
    const goals = await readdir(join(root, session)).catch(() => [])
    for (const goal of goals) {
      const before = await readdir(join(root, session, goal)).catch(() => [])
      await pruneDirectory(join(root, session, goal))
      const after = await readdir(join(root, session, goal)).catch(() => [])
      removed += Math.max(0, before.length - after.length)
    }
  }
  return removed
}
