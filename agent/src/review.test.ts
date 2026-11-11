// @tested-functions runReview, parseReviewReport, collectTranscript
import assert from 'node:assert/strict'
import { mkdtempSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import test from 'node:test'

import { listMemory } from './memory.js'
import {
  collectTranscript,
  parseReviewReport,
  runReview,
} from './review.js'

test('task review writes durable lessons and returns scoped improvements', async (t) => {
  const previous = process.env.MBFORGE_MEMORY_FILE
  process.env.MBFORGE_MEMORY_FILE = join(
    mkdtempSync(join(tmpdir(), 'mbforge-review-')),
    'MEMORY.md',
  )
  t.after(() => {
    if (previous === undefined) delete process.env.MBFORGE_MEMORY_FILE
    else process.env.MBFORGE_MEMORY_FILE = previous
  })

  const transcript = collectTranscript([
    {
      type: 'message',
      message: { role: 'user', content: 'Fix the review queue counts.' },
    },
    {
      type: 'message',
      message: {
        role: 'assistant',
        content: [{ type: 'text', text: 'The count was stale.' }],
      },
    },
  ])
  assert.match(transcript, /### user/)
  assert.match(transcript, /review queue counts/)

  const raw = [
    '```json',
    JSON.stringify({
      summary: 'The stale count came from a cached query.',
      lessons: [
        {
          type: 'feedback',
          content: 'Invalidate the review cache after a decision.',
        },
      ],
      improvements: [
        {
          title: 'Invalidate review counts after decisions',
          area: 'capability',
          problem: 'The count stayed stale after a decision.',
          change: 'Invalidate the count query in the decision mutation.',
          rationale: 'The next read should reflect the decision.',
          risk: 'One extra query.',
          files: ['frontend/src/api/query/hooks/useReview.ts'],
        },
      ],
    }),
    '```',
  ].join('\n')

  const result = await runReview(
    { cwd: 'C:/repo', transcript },
    async () => raw,
  )
  assert.equal(result.summary, 'The stale count came from a cached query.')
  assert.equal(result.warnings.length, 0)
  assert.equal(result.memories.length, 1)
  assert.equal(result.memories[0]?.type, 'feedback')
  assert.equal(result.improvements[0]?.area, 'capability')
  assert.equal(result.improvements[0]?.files.length, 1)

  const listed = await listMemory()
  assert.equal(listed.entries.length, 1)
  assert.equal(listed.entries[0]?.type, 'feedback')
  assert.match(listed.entries[0]?.content ?? '', /Invalidate the review cache/)
})

test('long task keeps the original goal and user clarifications', () => {
  const branch: unknown[] = [
    {
      type: 'message',
      message: { role: 'user', content: 'Original task goal must survive.' },
    },
    {
      type: 'message',
      message: { role: 'user', content: 'Clarification: keep the API stable.' },
    },
  ]
  for (let index = 0; index < 80; index += 1) {
    branch.push({
      type: 'message',
      message: {
        role: 'toolResult',
        toolName: 'bash',
        content: [{ type: 'text', text: 'x'.repeat(2_000) }],
      },
    })
  }
  branch.push({
    type: 'message',
    message: { role: 'user', content: 'Latest constraint: do not rename routes.' },
  })

  const transcript = collectTranscript(branch)
  assert.match(transcript, /Original task goal must survive/)
  assert.match(transcript, /Clarification: keep the API stable/)
  assert.match(transcript, /Latest constraint: do not rename routes/)
  assert.ok(transcript.length <= 12_000)
})

test('malformed reviewer output stays visible and writes no lessons', () => {
  const report = parseReviewReport('the reviewer was interrupted')
  assert.equal(report.lessons.length, 0)
  assert.equal(report.improvements.length, 0)
  assert.match(report.summary, /interrupted/)
  assert.match(report.warnings[0] ?? '', /not a JSON object/)
})
