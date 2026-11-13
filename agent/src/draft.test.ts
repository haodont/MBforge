// @tested-functions checkDraft, saveDraft, listDrafts, readDraft
import assert from 'node:assert/strict'
import { existsSync, mkdtempSync } from 'node:fs'
import { readFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import test from 'node:test'

import { checkDraft, listDrafts, readDraft, saveDraft } from './draft.js'

test('python drafts get a syntax check and are never executed', async () => {
  const marker = join(
    mkdtempSync(join(tmpdir(), 'mbforge-draft-run-')),
    'ran.txt',
  )
  const result = await checkDraft(
    `from pathlib import Path\nPath(r"${marker}").write_text("executed")\n`,
  )
  const syntax = result.checks.find((check) => check.name === 'syntax')
  assert.ok(syntax)
  if (syntax.status !== 'unavailable') assert.equal(syntax.status, 'ok')
  assert.equal(
    existsSync(marker),
    false,
    'checkDraft must not execute the draft',
  )

  const invalid = await checkDraft('def broken(:\n    pass\n')
  const invalidSyntax = invalid.checks.find((check) => check.name === 'syntax')
  if (invalidSyntax?.status !== 'unavailable') {
    assert.equal(invalidSyntax?.status, 'error')
  }
})

test('typescript, javascript and json get syntax checks; other languages are explicitly unchecked', async () => {
  const ts = await checkDraft('const value: number = 1\n', 'typescript')
  const tsCheck = ts.checks[0]
  assert.equal(tsCheck?.name, 'typescript')
  if (tsCheck?.status !== 'unavailable') assert.equal(tsCheck?.status, 'ok')

  const badTs = await checkDraft('const value: = 1\n', 'typescript')
  assert.equal(badTs.checks[0]?.name, 'typescript')
  if (badTs.checks[0]?.status !== 'unavailable') {
    assert.equal(badTs.checks[0]?.status, 'error')
  }

  const js = await checkDraft('function f() { return 1 }\n', 'javascript')
  assert.equal(js.checks[0]?.name, 'javascript')
  if (js.checks[0]?.status !== 'unavailable')
    assert.equal(js.checks[0]?.status, 'ok')

  assert.equal(
    (await checkDraft('{"ok": true}\n', 'json')).checks[0]?.status,
    'ok',
  )
  assert.equal(
    (await checkDraft('{"ok":\n', 'json')).checks[0]?.status,
    'error',
  )
  assert.equal(
    (await checkDraft('select 1;\n', 'sql')).checks[0]?.status,
    'unavailable',
  )
})

test('saved drafts round-trip through list and read', async () => {
  const root = mkdtempSync(join(tmpdir(), 'mbforge-drafts-'))
  const previous = process.env.MBFORGE_DRAFT_DIR
  process.env.MBFORGE_DRAFT_DIR = root
  try {
    const record = await saveDraft({
      code: 'def add(a, b):\n    return a + b\n',
      language: 'python',
      target_path: 'src/mbforge/example.py',
      summary: 'Small helper',
    })
    assert.match(record.id, /^draft-[0-9a-f]{8}$/)
    assert.equal(record.target_path, 'src/mbforge/example.py')
    assert.equal(record.lines, 2)
    assert.ok(record.file.startsWith(root))
    assert.equal(existsSync(record.file), true)

    const listed = await listDrafts()
    assert.equal(listed[0]?.id, record.id)
    assert.equal(listed[0]?.summary, 'Small helper')

    const read = await readDraft(record.id)
    assert.equal(read.record.id, record.id)
    assert.match(read.code, /def add\(a, b\):/)
    assert.equal(await readFile(record.file, 'utf8'), read.code)
  } finally {
    if (previous === undefined) delete process.env.MBFORGE_DRAFT_DIR
    else process.env.MBFORGE_DRAFT_DIR = previous
  }
})
