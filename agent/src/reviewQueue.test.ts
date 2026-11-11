// @tested-functions enqueueReviewJob, claimNextReview, finishReviewJob, failReviewJob
import assert from 'node:assert/strict'
import { mkdtempSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import test from 'node:test'

import type { GoalReviewJob } from './goal.js'
import {
  claimNextReview,
  enqueueReviewJob,
  failReviewJob,
  finishReviewJob,
  retryReviewJob,
  listReviewJobs,
  reviewQueueFilePath,
} from './reviewQueue.js'

const job: GoalReviewJob = {
  goalId: 'goal-1234',
  cwd: 'C:/repo',
  transcript: 'goal transcript',
}

function queueFile(t: test.TestContext): string {
  const previous = process.env.MBFORGE_REVIEW_QUEUE_FILE
  const path = join(
    mkdtempSync(join(tmpdir(), 'mbforge-review-queue-')),
    'QUEUE.json',
  )
  process.env.MBFORGE_REVIEW_QUEUE_FILE = path
  t.after(() => {
    if (previous === undefined) delete process.env.MBFORGE_REVIEW_QUEUE_FILE
    else process.env.MBFORGE_REVIEW_QUEUE_FILE = previous
  })
  assert.equal(reviewQueueFilePath(), path)
  return path
}

test('review queue persists, deduplicates, claims, and finishes a goal', async (t) => {
  queueFile(t)

  await enqueueReviewJob(job)
  await enqueueReviewJob(job)
  const listed = await listReviewJobs()
  assert.equal(listed.length, 1)
  assert.equal(listed[0]?.status, 'queued')

  const claimed = await claimNextReview()
  assert.equal(claimed?.goalId, 'goal-1234')
  assert.equal(claimed?.status, 'running')
  assert.equal(claimed?.attempts, 1)

  // A simulated restart sees the running job as queued again.
  const recovered = await listReviewJobs()
  assert.equal(recovered[0]?.status, 'queued')
  assert.equal(recovered[0]?.attempts, 1)

  const second = await claimNextReview()
  assert.equal(second?.attempts, 2)
  await finishReviewJob(second?.id ?? '')
  assert.deepEqual(await listReviewJobs(), [])
})

test('a failed review remains visible for inspection', async (t) => {
  queueFile(t)
  await enqueueReviewJob(job)
  const claimed = await claimNextReview()
  await failReviewJob(claimed?.id ?? '', 'reviewer timed out')

  const listed = await listReviewJobs()
  assert.equal(listed[0]?.status, 'failed')
  assert.equal(listed[0]?.error, 'reviewer timed out')
  assert.equal(await claimNextReview(), undefined)

  assert.equal(await retryReviewJob(claimed?.id ?? ''), true)
  const retried = await listReviewJobs()
  assert.equal(retried[0]?.status, 'queued')
  assert.equal(retried[0]?.attempts, 0)
  const reclaimed = await claimNextReview()
  assert.equal(reclaimed?.goalId, 'goal-1234')
  assert.equal(reclaimed?.attempts, 1)
  await finishReviewJob(reclaimed?.id ?? '')
})
