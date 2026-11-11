import { randomUUID } from 'node:crypto'
import { existsSync } from 'node:fs'
import { mkdir, readFile, rename, unlink, writeFile } from 'node:fs/promises'
import { dirname, join, resolve } from 'node:path'

import { getAgentDir } from '@earendil-works/pi-coding-agent'

import type { GoalReviewJob } from './goal.js'

const QUEUE_FILE_NAME = 'GOAL_REVIEW_QUEUE.json'
const MAX_QUEUE_JOBS = 50
const MAX_ATTEMPTS = 3

export type ReviewJobStatus = 'queued' | 'running' | 'failed'

export interface QueuedGoalReview extends GoalReviewJob {
  id: string
  created_at: string
  attempts: number
  status: ReviewJobStatus
  error?: string
}

interface ReviewQueueState {
  version: 1
  jobs: QueuedGoalReview[]
}

export function reviewQueueFilePath(): string {
  const override = process.env.MBFORGE_REVIEW_QUEUE_FILE?.trim()
  return override ? resolve(override) : join(getAgentDir(), QUEUE_FILE_NAME)
}

async function writeQueue(path: string, state: ReviewQueueState): Promise<void> {
  await mkdir(dirname(path), { recursive: true, mode: 0o700 })
  const temporary = `${path}.${process.pid}.${Date.now()}.tmp`
  try {
    await writeFile(temporary, `${JSON.stringify(state, null, 2)}\n`, {
      encoding: 'utf8',
      mode: 0o600,
    })
    await rename(temporary, path)
  } catch (error) {
    try {
      await unlink(temporary)
    } catch {
      // Best effort cleanup; preserve the original write error.
    }
    throw error
  }
}

async function readQueue(path: string): Promise<ReviewQueueState> {
  if (!existsSync(path)) return { version: 1, jobs: [] }
  const raw = (await readFile(path, 'utf8')).replace(/^\uFEFF/, '')
  if (!raw.trim()) return { version: 1, jobs: [] }
  let parsed: unknown
  try {
    parsed = JSON.parse(raw)
  } catch (error) {
    throw new Error(`Review queue is not valid JSON: ${path}`, { cause: error })
  }
  if (typeof parsed !== 'object' || parsed === null) {
    throw new Error(`Review queue has an invalid shape: ${path}`)
  }
  const rows = (parsed as { jobs?: unknown }).jobs
  if (!Array.isArray(rows)) {
    throw new Error(`Review queue has an invalid shape: ${path}`)
  }
  const jobs = rows
    .filter((row): row is QueuedGoalReview => {
      if (typeof row !== 'object' || row === null || Array.isArray(row)) return false
      const item = row as Partial<QueuedGoalReview>
      return (
        typeof item.id === 'string' &&
        typeof item.goalId === 'string' &&
        typeof item.cwd === 'string' &&
        typeof item.transcript === 'string' &&
        typeof item.status === 'string'
      )
    })
    .map((job) => {
      if (job.status !== 'running') return job
      if (job.attempts >= MAX_ATTEMPTS) {
        return { ...job, status: 'failed' as const, error: 'interrupted too many times' }
      }
      return { ...job, status: 'queued' as const }
    })
  return { version: 1, jobs }
}

let writeChain: Promise<unknown> = Promise.resolve()

function serialize<T>(operation: () => Promise<T>): Promise<T> {
  const run = writeChain.then(operation)
  writeChain = run.then(
    () => undefined,
    () => undefined,
  )
  return run
}

/** Add one goal review; the same goal is never queued twice. */
export async function enqueueReviewJob(job: GoalReviewJob): Promise<void> {
  const path = reviewQueueFilePath()
  await serialize(async () => {
    const state = await readQueue(path)
    if (state.jobs.some((item) => item.goalId === job.goalId)) return
    const item: QueuedGoalReview = {
      ...job,
      id: `review-${randomUUID().slice(0, 8)}`,
      created_at: new Date().toISOString(),
      attempts: 0,
      status: 'queued',
    }
    state.jobs = [item, ...state.jobs].slice(0, MAX_QUEUE_JOBS)
    await writeQueue(path, state)
  })
}

/** Claim the oldest queued review, or return nothing when the queue is empty. */
export async function claimNextReview(): Promise<QueuedGoalReview | undefined> {
  const path = reviewQueueFilePath()
  return serialize(async () => {
    const state = await readQueue(path)
    const item = [...state.jobs]
      .reverse()
      .find((job) => job.status === 'queued')
    if (!item) return undefined
    item.status = 'running'
    item.attempts += 1
    item.error = undefined
    await writeQueue(path, state)
    return item
  })
}

/** Remove a completed review from the queue. */
export async function finishReviewJob(id: string): Promise<void> {
  const path = reviewQueueFilePath()
  await serialize(async () => {
    const state = await readQueue(path)
    state.jobs = state.jobs.filter((job) => job.id !== id)
    await writeQueue(path, state)
  })
}

/** Keep a failed review for inspection instead of silently dropping it. */
export async function failReviewJob(id: string, error: string): Promise<void> {
  const path = reviewQueueFilePath()
  await serialize(async () => {
    const state = await readQueue(path)
    const item = state.jobs.find((job) => job.id === id)
    if (!item) return
    item.status = 'failed'
    item.error = error.slice(0, 2_000)
    await writeQueue(path, state)
  })
}

/** Requeue a permanently failed review for one manual retry. */
export async function retryReviewJob(id: string): Promise<boolean> {
  const path = reviewQueueFilePath()
  return serialize(async () => {
    const state = await readQueue(path)
    const item = state.jobs.find((job) => job.id === id && job.status === 'failed')
    if (!item) return false
    item.status = 'queued'
    item.attempts = 0
    item.error = undefined
    await writeQueue(path, state)
    return true
  })
}

export async function listReviewJobs(): Promise<QueuedGoalReview[]> {
  return (await readQueue(reviewQueueFilePath())).jobs
}
