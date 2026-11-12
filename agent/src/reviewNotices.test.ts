// @tested-functions ReviewNoticeQueue
import assert from 'node:assert/strict'
import test from 'node:test'

import { ReviewNoticeQueue } from './reviewNotices.js'

test('review notices wait for the foreground goal to end', () => {
  const queue = new ReviewNoticeQueue()
  const first = {
    reviewId: 'review-1',
    content: 'first',
    details: { goalId: 'goal-1' },
  }
  const second = {
    reviewId: 'review-2',
    content: 'second',
    details: { goalId: 'goal-2' },
  }

  queue.enqueue(first)
  queue.enqueue(second)
  assert.equal(queue.size, 2)
  assert.deepEqual(queue.drain(true), [])
  assert.equal(queue.size, 2)

  queue.remove('review-1')
  assert.equal(queue.size, 1)
  assert.deepEqual(queue.drain(false), [second])
  assert.equal(queue.size, 0)

  queue.enqueue(first)
  assert.deepEqual(queue.drain(false), [first])
})
