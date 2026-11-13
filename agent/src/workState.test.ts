// @tested-functions addWorkThread, updateWorkThread, closeWorkThread, readWorkState, workStateSystemPrompt, workStateTool
import assert from 'node:assert/strict'
import { mkdtempSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import test from 'node:test'

import {
  addWorkThread,
  closeWorkThread,
  readWorkState,
  updateWorkThread,
  workStateSystemPrompt,
  workStateTool,
} from './workState.js'

function useTempWorkState(t: test.TestContext): string {
  const previous = process.env.MBFORGE_WORK_STATE_FILE
  const path = join(
    mkdtempSync(join(tmpdir(), 'mbforge-work-')),
    'WORK_STATE.json',
  )
  process.env.MBFORGE_WORK_STATE_FILE = path
  t.after(() => {
    if (previous === undefined) delete process.env.MBFORGE_WORK_STATE_FILE
    else process.env.MBFORGE_WORK_STATE_FILE = previous
  })
  return path
}

test('work ledger persists across sessions and maintains threads', async (t) => {
  useTempWorkState(t)

  // A fresh library adds no prompt noise.
  assert.equal(await workStateSystemPrompt(), '')
  assert.deepEqual((await readWorkState()).threads, [])

  const hypothesis = await addWorkThread({
    kind: 'hypothesis',
    title: 'R1 = CF3 improves potency',
    detail: 'Series A trend suggests electron-withdrawing R1.',
    refs: ['ev-1'],
  })
  const followUp = await addWorkThread({
    kind: 'follow_up',
    title: 'await synthesis of compound 12',
  })
  assert.match(hypothesis.id, /^wt-[0-9a-f]{8}$/)

  // Durability: a "new session" reads the same process-independent file.
  const reread = await readWorkState()
  assert.equal(reread.threads.length, 2)

  const prompt = await workStateSystemPrompt()
  assert.match(prompt, /R1 = CF3 improves potency/)
  assert.match(prompt, /await synthesis of compound 12/)

  // Update and close; a closed thread leaves the open prompt.
  await updateWorkThread(hypothesis.id, { detail: 'Refined after docking.' })
  await closeWorkThread(followUp.id)
  const after = await readWorkState()
  assert.equal(
    after.threads.find((thread) => thread.id === followUp.id)?.status,
    'done',
  )
  assert.equal(
    after.threads.find((thread) => thread.id === hypothesis.id)?.detail,
    'Refined after docking.',
  )
  const promptAfterClose = await workStateSystemPrompt()
  assert.doesNotMatch(promptAfterClose, /await synthesis of compound 12/)

  // The tool dispatches list/add/close over the same ledger.
  const tool = workStateTool()
  const added = await tool.execute(
    'call-1',
    { action: 'add', kind: 'decision', title: 'Keep scaffold fixed', refs: [] },
    undefined,
    undefined,
    {} as never,
  )
  const addedId = (added.details as { id: string }).id
  const listed = await tool.execute(
    'call-2',
    { action: 'list' },
    undefined,
    undefined,
    {} as never,
  )
  const openItems = (listed.details as { items: Array<{ id: string }> }).items
  assert.ok(openItems.some((item) => item.id === addedId))
  assert.ok(
    !openItems.some((item) => item.id === followUp.id),
    'list defaults to open threads',
  )
  await tool.execute(
    'call-3',
    { action: 'close', id: addedId },
    undefined,
    undefined,
    {} as never,
  )
  assert.equal(
    (await readWorkState()).threads.find((thread) => thread.id === addedId)
      ?.status,
    'done',
  )

  await assert.rejects(
    addWorkThread({ kind: 'note', title: 'x'.repeat(161) }),
    /at most 160/,
  )
  await assert.rejects(
    updateWorkThread('wt-00000000', { title: 'gone' }),
    /not found/,
  )
})

test('the work ledger is bounded so it cannot grow without limit', async (t) => {
  useTempWorkState(t)
  for (let index = 0; index < 55; index += 1) {
    await addWorkThread({ kind: 'note', title: `note ${index}` })
  }
  const state = await readWorkState()
  assert.equal(state.threads.length, 50)
  // Newest first: the most recent note survives, the oldest is pruned.
  assert.equal(state.threads[0].title, 'note 54')
})
