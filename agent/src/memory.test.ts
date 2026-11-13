// @tested-functions ensureMemoryFile, readMemory, readColdMemory, memorySystemPrompt, appendMemory, updateMemory, forgetMemory, listMemory, listEphemeralMemory, memoryTool, memoryEphemeralTool
import assert from 'node:assert/strict'
import { mkdtempSync, readFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import test from 'node:test'

import {
  appendMemory,
  ensureMemoryFile,
  forgetMemory,
  listEphemeralMemory,
  listMemory,
  memoryArchivePath,
  memoryEphemeralPath,
  memoryStatePath,
  memorySystemPrompt,
  memoryTool,
  readColdMemory,
  readMemory,
  setMemoryRuntime,
  updateMemory,
  waitForMemoryMaintenance,
} from './memory.js'

function useTempMemory(t: test.TestContext): string {
  const previous = process.env.MBFORGE_MEMORY_FILE
  const path = join(mkdtempSync(join(tmpdir(), 'mbforge-memory-')), 'MEMORY.md')
  process.env.MBFORGE_MEMORY_FILE = path
  t.after(() => {
    if (previous === undefined) delete process.env.MBFORGE_MEMORY_FILE
    else process.env.MBFORGE_MEMORY_FILE = previous
  })
  return path
}

test('ephemeral notes are isolated, editable, and removable', async (t) => {
  const path = useTempMemory(t)

  assert.equal(await ensureMemoryFile(), path)
  const first = await appendMemory('Prefer concise Chinese answers.', 'user')
  assert.equal(first.path, memoryEphemeralPath())
  assert.match(first.id, /^u-[0-9a-f]{8}$/)

  assert.equal((await listEphemeralMemory()).entries.length, 1)
  assert.equal((await listMemory()).entries.length, 0)
  assert.doesNotMatch(
    await memorySystemPrompt(),
    /Prefer concise Chinese answers/,
  )

  const updated = await updateMemory(
    first.id,
    'Prefer concise English answers.',
    'feedback',
  )
  assert.match(updated.id, /^f-[0-9a-f]{8}$/)
  assert.equal(updated.previous_id, first.id)

  const ephemeral = await listEphemeralMemory()
  assert.deepEqual(
    ephemeral.entries.map((entry) => [entry.id, entry.type, entry.content]),
    [[updated.id, 'feedback', 'Prefer concise English answers.']],
  )

  await forgetMemory(updated.id)
  assert.equal((await listEphemeralMemory()).entries.length, 0)
  await assert.rejects(forgetMemory(updated.id), /not found/)
  await assert.rejects(updateMemory(first.id, 'gone'), /not found/)
  await assert.rejects(updateMemory(first.id), /requires content or type/)

  await assert.rejects(
    appendMemory('x'.repeat(2_001), 'project'),
    /longer than 2000 characters/,
  )
  await assert.rejects(appendMemory('   ', 'project'), /empty/)
  await assert.rejects(
    async () => appendMemory('fact', ''),
    /type must be one of/,
  )
})

test('seventeen ephemeral notes compact into hot and cold layers', async (t) => {
  const path = useTempMemory(t)

  for (let batch = 0; batch < 3; batch += 1) {
    for (let index = 0; index < 16; index += 1) {
      await appendMemory(`project ${batch}-${index}`, 'project')
    }
    await appendMemory(`preference ${batch}`, 'user')
  }

  assert.equal((await listEphemeralMemory()).entries.length, 0)
  const hot = await readMemory()
  const cold = await readColdMemory()
  assert.match(hot, /project 0-0/)
  assert.match(hot, /preference 2/)
  assert.match(cold, /preference 0/)
  assert.doesNotMatch(cold, /preference 2/)

  const state = JSON.parse(readFileSync(memoryStatePath(), 'utf8')) as {
    hot_updates: number
  }
  assert.equal(state.hot_updates, 3)
  assert.match(readFileSync(memoryArchivePath(path), 'utf8'), /project 0-0/)

  await appendMemory('ephemeral-only note', 'project')
  assert.doesNotMatch(await memorySystemPrompt(), /ephemeral-only note/)
  const prompt = await memorySystemPrompt()
  assert.match(prompt, /### Cold memory/)
  assert.match(prompt, /### Hot memory/)
  assert.match(prompt, /preference 0/)
})

test('memory tools list active layers and inspect ephemeral notes separately', async (t) => {
  useTempMemory(t)
  const tool = memoryTool()
  assert.equal(tool.name, 'memory')

  const added = await tool.execute(
    'call-1',
    { action: 'add', content: 'Prefer concise Chinese answers.', type: 'user' },
    undefined,
    undefined,
    {} as never,
  )
  const addedDetails = added.details as { id: string; ephemeral_count: number }
  assert.match(addedDetails.id, /^u-[0-9a-f]{8}$/)
  assert.equal(addedDetails.ephemeral_count, 1)

  const listed = await tool.execute(
    'call-2',
    { action: 'list' },
    undefined,
    undefined,
    {} as never,
  )
  const listedDetails = listed.details as {
    ephemeral_count: number
    hot: string
    cold: string
  }
  assert.equal(listedDetails.ephemeral_count, 1)
  assert.doesNotMatch(
    JSON.stringify(listedDetails),
    /Prefer concise Chinese answers/,
  )
  assert.match(listedDetails.hot, /# MBForge memory/)

  const ephemeral = await tool.execute(
    'call-3',
    { action: 'ephemeral' },
    undefined,
    undefined,
    {} as never,
  )
  const ephemeralDetails = ephemeral.details as {
    count: number
    entries: Array<{ id: string; content: string }>
  }
  assert.equal(ephemeralDetails.count, 1)
  assert.equal(ephemeralDetails.entries[0].id, addedDetails.id)
  assert.equal(
    ephemeralDetails.entries[0].content,
    'Prefer concise Chinese answers.',
  )

  const updated = await tool.execute(
    'call-4',
    {
      action: 'update',
      id: addedDetails.id,
      content: 'Prefer concise English answers.',
    },
    undefined,
    undefined,
    {} as never,
  )
  const updatedDetails = updated.details as {
    id: string
    previous_id: string
    updated: boolean
  }
  assert.equal(updatedDetails.previous_id, addedDetails.id)
  assert.equal(updatedDetails.updated, true)

  const deleted = await tool.execute(
    'call-5',
    { action: 'delete', id: updatedDetails.id },
    undefined,
    undefined,
    {} as never,
  )
  assert.equal((deleted.details as { removed: boolean }).removed, true)
  assert.equal((await listEphemeralMemory()).entries.length, 0)

  await assert.rejects(
    async () =>
      tool.execute(
        'call-6',
        { action: 'add' },
        undefined,
        undefined,
        {} as never,
      ),
    /requires content/,
  )
  await assert.rejects(
    async () =>
      tool.execute(
        'call-7',
        { action: 'delete' },
        undefined,
        undefined,
        {} as never,
      ),
    /requires id/,
  )
})

test('background maintenance compresses ephemeral and hot memory with the model', async (t) => {
  const path = useTempMemory(t)
  const fakeModel = { id: 'fake', provider: 'fake' } as never
  const fakeRegistry = {
    complete: async (
      _model: unknown,
      context: { messages: Array<{ content: string }> },
    ) => {
      const prompt = context.messages[0]?.content ?? ''
      const text = prompt.includes('"cold_rule"')
        ? JSON.stringify({
            hot: [{ type: 'user', content: 'model hot preference' }],
            cold_rule: 'model cold rule',
          })
        : JSON.stringify([
            { type: 'project', content: 'model ephemeral compression' },
          ])
      return { content: [{ type: 'text', text }] }
    },
  }
  setMemoryRuntime(fakeModel, fakeRegistry as never)
  t.after(() => setMemoryRuntime(undefined, fakeRegistry as never))

  for (let batch = 0; batch < 3; batch += 1) {
    for (let index = 0; index < 17; index += 1) {
      await appendMemory(`project ${batch}-${index}`, 'project')
    }
    await new Promise((resolve) => setImmediate(resolve))
    await waitForMemoryMaintenance()
  }

  assert.equal((await listEphemeralMemory()).entries.length, 0)
  const hot = await readMemory()
  assert.match(hot, /model hot preference/)
  assert.doesNotMatch(hot, /project 0-0/)
  assert.match(await readColdMemory(), /model cold rule/)
  assert.match(readFileSync(memoryArchivePath(path), 'utf8'), /project 0-0/)

  const state = JSON.parse(readFileSync(memoryStatePath(), 'utf8')) as {
    hot_updates: number
    pending: boolean
  }
  assert.equal(state.hot_updates, 0)
  assert.equal(state.pending, false)

  const prompt = await memorySystemPrompt()
  assert.match(prompt, /model cold rule/)
  assert.match(prompt, /model hot preference/)
  assert.doesNotMatch(prompt, /project 3-16/)
})
