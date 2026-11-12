import { randomUUID } from 'node:crypto'
import { join, resolve } from 'node:path'

import { getAgentDir } from '@earendil-works/pi-coding-agent'

import type { GoalReviewJob } from './goal.js'
import { atomicWrite, createSerializer, readJsonFile } from './localStore.js'

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

async function readQueue(path: string): Promise<ReviewQueueState> {
  let parsed: unknown
  try {
    parsed = await readJsonFile(path)
  } catch (error) {
    throw new Error(`Review queue is not valid JSON: ${path}`, { cause: error })
  }
  if (parsed === undefined) return { version: 1, jobs: [] }
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

const serialize = createSerializer()

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
    await atomicWrite(path, `${JSON.stringify(state, null, 2)}\n`)
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
    await atomicWrite(path, `${JSON.stringify(state, null, 2)}\n`)
    return item
  })
}

/** Remove a completed review from the queue. */
export async function finishReviewJob(id: string): Promise<void> {
  const path = reviewQueueFilePath()
  await serialize(async () => {
    const state = await readQueue(path)
    state.jobs = state.jobs.filter((job) => job.id !== id)
    await atomicWrite(path, `${JSON.stringify(state, null, 2)}\n`)
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
    await atomicWrite(path, `${JSON.stringify(state, null, 2)}\n`)
  })
}

/** Requeue a permanently failed review for one manual retry.
 *
 * The reference may be the queue id (`review-…`) or the goal id shown in the
 * failure notice (`goal-…`); the notice only shows the latter, so accepting
 * both avoids a dead-end retry.
 */
export async function retryReviewJob(
  reference: string,
): Promise<QueuedGoalReview | undefined> {
  const path = reviewQueueFilePath()
  return serialize(async () => {
    const state = await readQueue(path)
    const item = state.jobs.find(
      (job) =>
        job.status === 'failed' &&
        (job.id === reference || job.goalId === reference),
    )
    if (!item) return undefined
    item.status = 'queued'
    item.attempts = 0
    item.error = undefined
    await atomicWrite(path, `${JSON.stringify(state, null, 2)}\n`)
    return item
  })
}

export async function listReviewJobs(): Promise<QueuedGoalReview[]> {
  return (await readQueue(reviewQueueFilePath())).jobs
}
