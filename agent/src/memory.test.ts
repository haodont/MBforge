// @tested-functions ensureMemoryFile, readMemory, memorySystemPrompt, appendMemory, updateMemory, forgetMemory, listMemory, memoryTool, compactMemory
import assert from 'node:assert/strict'
import { mkdtempSync, readFileSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import test from 'node:test'

import {
  appendMemory,
  ensureMemoryFile,
  forgetMemory,
  listMemory,
  memoryArchivePath,
  memorySystemPrompt,
  memoryTool,
  readMemory,
  updateMemory,
} from './memory.js'

test('typed local memory is created, deduplicated, injected, and removable', async (t) => {
  const previous = process.env.MBFORGE_MEMORY_FILE
  const path = join(mkdtempSync(join(tmpdir(), 'mbforge-memory-')), 'MEMORY.md')
  process.env.MBFORGE_MEMORY_FILE = path
  t.after(() => {
    if (previous === undefined) delete process.env.MBFORGE_MEMORY_FILE
    else process.env.MBFORGE_MEMORY_FILE = previous
  })

  assert.equal(await ensureMemoryFile(), path)
  assert.equal((await memorySystemPrompt()).trim(), '')
  assert.match(await readMemory(), /# MBForge memory/)

  const first = await appendMemory('Prefer concise Chinese answers.', 'user')
  assert.match(first.id, /^u-[0-9a-f]{8}$/)
  assert.equal(first.type, 'user')
  assert.match(first.entry, /^\- \[u-[0-9a-f]{8}\] \d{4}-\d{2}-\d{2}: /)

  const duplicate = await appendMemory('Prefer concise Chinese answers.', 'user')
  assert.equal(duplicate.id, first.id)

  const second = await appendMemory(
    'The library is at D:\\data\\mbforge.',
    'project',
  )
  assert.match(second.id, /^p-[0-9a-f]{8}$/)

  const updated = await updateMemory(
    second.id,
    'The library is at E:\\data\\mbforge.',
    'reference',
  )
  assert.match(updated.id, /^r-[0-9a-f]{8}$/)
  assert.equal(updated.previous_id, second.id)
  assert.equal(updated.type, 'reference')

  const text = await readMemory()
  assert.match(text, /## user/)
  assert.match(text, /## project/)
  assert.match(text, /Prefer concise Chinese answers\./)
  assert.match(text, /E:\\data\\mbforge\./)
  assert.doesNotMatch(text, /D:\\data\\mbforge\./)

  const prompt = await memorySystemPrompt()
  assert.match(prompt, /## Local memory/)
  assert.match(prompt, /never as source evidence/)
  assert.match(prompt, /## user/)
  assert.match(prompt, /Prefer concise Chinese answers\./)

  await forgetMemory(first.id)
  const afterForget = await readMemory()
  assert.doesNotMatch(afterForget, /Prefer concise Chinese answers\./)
  assert.match(afterForget, /E:\\data\\mbforge\./)
  await assert.rejects(forgetMemory(first.id), /not found/)
  await assert.rejects(updateMemory(second.id, 'gone'), /not found/)
  await assert.rejects(updateMemory(updated.id), /requires content or type/)

  await assert.rejects(
    appendMemory('x'.repeat(2_001), 'project'),
    /longer than 2000 characters/,
  )
  await assert.rejects(appendMemory('   ', 'project'), /empty/)
  await assert.rejects(
    async () => appendMemory('fact', 'unknown'),
    /type must be one of/,
  )

  const listed = await listMemory()
  assert.deepEqual(
    listed.entries.map((entry) => [entry.id, entry.type]),
    [
      [updated.id, 'reference'],
    ],
  )
  assert.match(listed.entries[0].date, /^\d{4}-\d{2}-\d{2}$/)
  assert.equal(listed.entries[0].content, 'The library is at E:\\data\\mbforge.')

  writeFileSync(path, '你'.repeat(6_000), 'utf8')
  const truncated = await readMemory()
  assert.equal(truncated.includes('\uFFFD'), false)
})

test('memory compaction archives old entries and keeps the active file bounded', async (t) => {
  const previous = process.env.MBFORGE_MEMORY_FILE
  const path = join(
    mkdtempSync(join(tmpdir(), 'mbforge-memory-compact-')),
    'MEMORY.md',
  )
  process.env.MBFORGE_MEMORY_FILE = path
  t.after(() => {
    if (previous === undefined) delete process.env.MBFORGE_MEMORY_FILE
    else process.env.MBFORGE_MEMORY_FILE = previous
  })

  for (let index = 0; index < 12; index += 1) {
    await appendMemory(`project note ${index} ${'x'.repeat(1_900)}`, 'project')
  }

  const active = readFileSync(path, 'utf8')
  assert.ok(Buffer.byteLength(active, 'utf8') <= 16 * 1024)
  assert.match(active, /project note 11 /)

  const archive = readFileSync(memoryArchivePath(path), 'utf8')
  assert.match(archive, /project note 0 /)

  const readPath = join(
    mkdtempSync(join(tmpdir(), 'mbforge-memory-read-')),
    'MEMORY.md',
  )
  process.env.MBFORGE_MEMORY_FILE = readPath
  const entries = Array.from({ length: 10 }, (_, index) => {
    const id = `p-${index.toString(16).padStart(8, '0')}`
    return `- [${id}] 2026-01-01: project read note ${index} ${'x'.repeat(1_800)}`
  })
  writeFileSync(
    readPath,
    `# MBForge memory\n\n## project\n\n${entries.join('\n')}\n`,
    'utf8',
  )

  const compacted = await readMemory()
  const readActive = readFileSync(readPath, 'utf8')
  assert.ok(Buffer.byteLength(readActive, 'utf8') <= 16 * 1024)
  assert.match(compacted, /project read note 9 /)
  assert.match(
    readFileSync(memoryArchivePath(readPath), 'utf8'),
    /project read note 0 /,
  )
})

test('the memory tool stores, lists, and deletes notes through one action switch', async (t) => {
  const previous = process.env.MBFORGE_MEMORY_FILE
  const path = join(mkdtempSync(join(tmpdir(), 'mbforge-memory-tool-')), 'MEMORY.md')
  process.env.MBFORGE_MEMORY_FILE = path
  t.after(() => {
    if (previous === undefined) delete process.env.MBFORGE_MEMORY_FILE
    else process.env.MBFORGE_MEMORY_FILE = previous
  })

  const tool = memoryTool()
  assert.equal(tool.name, 'memory')

  const added = await tool.execute(
    'call-1',
    { action: 'add', content: 'Prefer concise Chinese answers.', type: 'user' },
    undefined,
    undefined,
    {} as never,
  )
  const addedDetails = added.details as { id: string; type: string }
  assert.match(addedDetails.id, /^u-[0-9a-f]{8}$/)
  assert.equal(addedDetails.type, 'user')

  const listed = await tool.execute(
    'call-2',
    { action: 'list' },
    undefined,
    undefined,
    {} as never,
  )
  const listedDetails = listed.details as { entries: Array<{ id: string; content: string }> }
  assert.equal(listedDetails.entries.length, 1)
  assert.equal(listedDetails.entries[0].id, addedDetails.id)
  assert.equal(listedDetails.entries[0].content, 'Prefer concise Chinese answers.')

  const updated = await tool.execute(
    'call-2a',
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
  assert.match(updatedDetails.id, /^u-[0-9a-f]{8}$/)
  assert.equal(updatedDetails.updated, true)

  const listedUpdated = await tool.execute(
    'call-2b',
    { action: 'list' },
    undefined,
    undefined,
    {} as never,
  )
  const listedUpdatedDetails = listedUpdated.details as {
    entries: Array<{ id: string; content: string }>
  }
  assert.equal(listedUpdatedDetails.entries.length, 1)
  assert.equal(listedUpdatedDetails.entries[0].id, updatedDetails.id)
  assert.equal(
    listedUpdatedDetails.entries[0].content,
    'Prefer concise English answers.',
  )

  const deleted = await tool.execute(
    'call-3',
    { action: 'delete', id: updatedDetails.id },
    undefined,
    undefined,
    {} as never,
  )
  assert.equal((deleted.details as { removed: boolean }).removed, true)
  assert.equal((await listMemory()).entries.length, 0)

  await assert.rejects(
    async () =>
      tool.execute('call-4', { action: 'add' }, undefined, undefined, {} as never),
    /requires content/,
  )
  await assert.rejects(
    async () =>
      tool.execute('call-5', { action: 'delete' }, undefined, undefined, {} as never),
    /requires id/,
  )
})
