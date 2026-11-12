// @tested-functions reconcileWorkThreads, addWorkThread, updateWorkThread
import assert from 'node:assert/strict'
import { mkdtempSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import test from 'node:test'

import { reconcileWorkThreads } from './workReconcile.js'
import { addWorkThread, readWorkState } from './workState.js'

function useTempWorkState(t: test.TestContext): void {
  const previous = process.env.MBFORGE_WORK_STATE_FILE
  process.env.MBFORGE_WORK_STATE_FILE = join(
    mkdtempSync(join(tmpdir(), 'mbforge-reconcile-')),
    'WORK_STATE.json',
  )
  t.after(() => {
    if (previous === undefined) delete process.env.MBFORGE_WORK_STATE_FILE
    else process.env.MBFORGE_WORK_STATE_FILE = previous
  })
}

type Handler = (payload: Record<string, unknown>) => unknown

function stubFetch(t: test.TestContext, handlers: Record<string, Handler>): void {
  const original = globalThis.fetch
  t.after(() => {
    globalThis.fetch = original
  })
  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const name = String(input).split('/api/v1/capabilities/')[1]
    const payload = JSON.parse(String(init?.body ?? '{}')) as Record<string, unknown>
    const data = handlers[name]?.(payload)
    if (data === undefined) {
      return new Response(JSON.stringify({ success: false }), { status: 500 })
    }
    return new Response(JSON.stringify({ success: true, data }), {
      status: 200,
      headers: { 'content-type': 'application/json' },
    })
  }) as typeof fetch
}

test('check reconciles linked follow_ups against server status', async (t) => {
  useTempWorkState(t)
  stubFetch(t, {
    runs: (payload) => {
      const id = String(payload.run_id)
      if (id === 'run-error') return undefined // unreachable
      const status = id === 'run-done' ? 'done' : id === 'run-failed' ? 'failed' : 'processing'
      return { status, nodes: [] }
    },
    list_review_queue: () => ({
      items: [
        { item_id: 'rev-confirmed', status: 'confirmed' },
        { item_id: 'rev-pending', status: 'pending' },
      ],
    }),
    document_read: () => ({ status: 'extracted' }),
  })

  const done = await addWorkThread({ kind: 'follow_up', title: 'await extract', link: { kind: 'run', id: 'run-done' } })
  const failed = await addWorkThread({ kind: 'follow_up', title: 'await patent', link: { kind: 'run', id: 'run-failed' } })
  const confirmed = await addWorkThread({ kind: 'follow_up', title: 'await review', link: { kind: 'review', id: 'rev-confirmed', sub: 'ai_review' } })
  const pending = await addWorkThread({ kind: 'follow_up', title: 'await decision', link: { kind: 'review', id: 'rev-pending', sub: 'ai_review' } })
  const doc = await addWorkThread({ kind: 'follow_up', title: 'await import', link: { kind: 'document', id: 'doc-x' } })
  const unreachable = await addWorkThread({ kind: 'follow_up', title: 'await gone', link: { kind: 'run', id: 'run-error' } })
  // A hypothesis with a link is not a follow_up: check must ignore it.
  const hypothesis = await addWorkThread({ kind: 'hypothesis', title: 'idea', link: { kind: 'run', id: 'run-done' } })

  const results = await reconcileWorkThreads()
  assert.equal(results.length, 6, 'only open follow_ups with a link are checked')

  const byId = new Map(results.map((result) => [result.id, result]))
  assert.equal(byId.get(done.id)?.outcome, 'closed')
  assert.equal(byId.get(failed.id)?.outcome, 'open')
  assert.equal(byId.get(confirmed.id)?.outcome, 'closed')
  assert.equal(byId.get(pending.id)?.outcome, 'open')
  assert.equal(byId.get(doc.id)?.outcome, 'open')
  assert.equal(byId.get(doc.id)?.status, 'extracted')
  assert.equal(byId.get(unreachable.id)?.outcome, 'unreachable')

  const state = await readWorkState()
  const statusOf = (id: string) => state.threads.find((thread) => thread.id === id)?.status
  assert.equal(statusOf(done.id), 'done', 'a done run closes its follow_up')
  assert.equal(statusOf(failed.id), 'open', 'a failed run needs the model, stays open')
  assert.equal(statusOf(confirmed.id), 'done')
  assert.equal(statusOf(pending.id), 'open')
  assert.equal(statusOf(hypothesis.id), 'open', 'a non-follow_up is never auto-closed')
  // The check annotates the thread so the next session sees the last result.
  assert.match(state.threads.find((thread) => thread.id === failed.id)?.check_note ?? '', /failed/)
  assert.ok(state.threads.find((thread) => thread.id === failed.id)?.last_checked)
})

test('check with no linked follow_ups is a no-op', async (t) => {
  useTempWorkState(t)
  await addWorkThread({ kind: 'note', title: 'no link' })
  const results = await reconcileWorkThreads()
  assert.deepEqual(results, [])
})