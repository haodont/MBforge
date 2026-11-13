// @tested-functions createRunWatcher, createRunNotifier
import assert from 'node:assert/strict'
import test from 'node:test'

import {
  createRunNotifier,
  createRunWatcher,
  type RunCompletion,
} from './runs.js'

interface SentMessage {
  message: { customType: string; content: unknown; details?: unknown }
  options?: { triggerTurn?: boolean; deliverAs?: string }
}

function jsonResponse(data: unknown): Response {
  return new Response(JSON.stringify({ success: true, data }), {
    status: 200,
    headers: { 'content-type': 'application/json' },
  })
}

function fakeCompletions(): {
  sent: SentMessage[]
  notifier: ReturnType<typeof createRunNotifier>
} {
  const sent: SentMessage[] = []
  const notifier = createRunNotifier({
    sendMessage: (message, options) => sent.push({ message, options }),
  })
  return { sent, notifier }
}

function completion(runId: string, status = 'done'): RunCompletion {
  return {
    runId,
    status,
    docId: `doc-${runId}`,
    message: `MBForge run ${runId} finished with status "${status}".`,
  }
}

test('a run watcher reports a terminal run once', async () => {
  const completed: RunCompletion[] = []
  let resolveCompleted: (() => void) | undefined
  const reported = new Promise<void>((resolve) => {
    resolveCompleted = resolve
  })
  let polls = 0
  const watcher = createRunWatcher(
    (result) => {
      completed.push(result)
      resolveCompleted?.()
    },
    {
      intervalMs: 5,
      fetchImpl: (async () => {
        polls += 1
        return jsonResponse({
          run_id: 'run-1',
          doc_id: 'doc-1',
          status: 'done',
          nodes: [
            { stage: 'extract', status: 'done' },
            { stage: 'markdown', status: 'done' },
          ],
        })
      }) as unknown as typeof fetch,
    },
  )

  watcher.watch('run-1')
  watcher.watch('run-1')
  assert.equal(polls, 1, 'a duplicate watch must not add a second poll')
  await reported
  watcher.stopAll()

  assert.equal(completed.length, 1)
  assert.equal(completed[0].runId, 'run-1')
  assert.match(completed[0].message, /markdown=done/)
})

test('a failed run completion carries the stage error', async () => {
  const completed: RunCompletion[] = []
  let resolveCompleted: (() => void) | undefined
  const reported = new Promise<void>((resolve) => {
    resolveCompleted = resolve
  })
  const watcher = createRunWatcher(
    (result) => {
      completed.push(result)
      resolveCompleted?.()
    },
    {
      intervalMs: 5,
      fetchImpl: (async () =>
        jsonResponse({
          run_id: 'run-failed',
          doc_id: 'doc-1',
          status: 'failed',
          nodes: [
            {
              stage: 'extract',
              status: 'failed',
              error: 'layout model missing',
            },
            { stage: 'markdown', status: 'failed' },
          ],
        })) as unknown as typeof fetch,
    },
  )

  watcher.watch('run-failed')
  await reported
  watcher.stopAll()

  assert.equal(completed.length, 1)
  assert.match(completed[0].message, /extract: layout model missing/)
  assert.match(completed[0].message, /run_control/)
})

test('completions are batched while busy and delivered once when idle', () => {
  const { sent, notifier } = fakeCompletions()

  notifier.markBusy()
  notifier.notify(completion('run-1'))
  notifier.notify(completion('run-2', 'failed'))
  notifier.notify(completion('run-1')) // duplicate run id is ignored
  assert.equal(sent.length, 0, 'no message may start a turn mid-run')

  notifier.markIdle()
  assert.equal(sent.length, 1, 'pending completions share one wake-up')
  assert.equal(sent[0].message.customType, 'mbforge.run')
  assert.match(String(sent[0].message.content), /run-1/)
  assert.match(String(sent[0].message.content), /run-2.*failed/s)
  assert.deepEqual(sent[0].options, { triggerTurn: true })
  assert.equal(
    'deliverAs' in (sent[0].options ?? {}),
    false,
    'queued delivery is what replays on session resume',
  )

  notifier.markIdle()
  assert.equal(sent.length, 1, 'a second settle must not resend anything')
  notifier.stop()
})

test('an idle completion is delivered immediately and only once', () => {
  const { sent, notifier } = fakeCompletions()

  notifier.notify(completion('run-3'))
  notifier.notify(completion('run-3'))

  assert.equal(sent.length, 1)
  assert.equal(sent[0].message.customType, 'mbforge.run')
  assert.match(String(sent[0].message.content), /run-3/)
  assert.deepEqual(sent[0].options, { triggerTurn: true })
  notifier.stop()
})

test('a stalled poll times out and the watcher polls again', async () => {
  const completed: RunCompletion[] = []
  let resolveCompleted: (() => void) | undefined
  const reported = new Promise<void>((resolve) => {
    resolveCompleted = resolve
  })
  let polls = 0
  const watcher = createRunWatcher(
    (result) => {
      completed.push(result)
      resolveCompleted?.()
    },
    {
      intervalMs: 5,
      timeoutMs: 30,
      fetchImpl: ((_input: RequestInfo | URL, init?: RequestInit) => {
        polls += 1
        if (polls === 1) {
          // A backend that accepts the connection but never answers.
          return new Promise<Response>((_resolve, reject) => {
            init?.signal?.addEventListener('abort', () =>
              reject(new Error('poll aborted')),
            )
          })
        }
        return Promise.resolve(
          jsonResponse({
            run_id: 'run-stall',
            doc_id: 'doc-1',
            status: 'done',
            nodes: [],
          }),
        )
      }) as unknown as typeof fetch,
    },
  )

  watcher.watch('run-stall')
  await reported
  watcher.stopAll()

  assert.equal(completed.length, 1)
  assert.ok(
    polls >= 2,
    'a hung request must not stop the watcher from retrying',
  )
})
