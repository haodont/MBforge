// @tested-functions proposeImprovement, listImprovements, completeImprovement
import assert from 'node:assert/strict'
import { mkdtempSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import test from 'node:test'

import {
  completeImprovement,
  listImprovements,
  proposeImprovement,
  type ImprovementInput,
} from './improvements.js'

const suggestion: ImprovementInput = {
  title: 'Use one visual capability',
  area: 'capability',
  problem: 'Two page-image capability tools duplicate the same work.',
  change: 'Merge the tools into one action-based capability.',
  rationale: 'Fewer tools and no base64 round trip.',
  risk: 'Existing prompts may still name the old action.',
  files: ['src/mbforge/service/capabilities/read.py'],
}

test('improvement approval gates storage and only approved items complete', async (t) => {
  const previous = process.env.MBFORGE_IMPROVEMENTS_FILE
  const path = join(
    mkdtempSync(join(tmpdir(), 'mbforge-improvements-')),
    'IMPROVEMENTS.json',
  )
  process.env.MBFORGE_IMPROVEMENTS_FILE = path
  t.after(() => {
    if (previous === undefined) delete process.env.MBFORGE_IMPROVEMENTS_FILE
    else process.env.MBFORGE_IMPROVEMENTS_FILE = previous
  })

  const base = {
    project: 'C:/repo',
    canEdit: true,
    hasUI: true,
  }
  const declined = await proposeImprovement(suggestion, {
    ...base,
    confirm: async () => false,
  })
  assert.equal(declined.approved, false)
  assert.equal(declined.executable, false)
  assert.equal(declined.status, 'rejected')
  assert.match(declined.message, /Do not implement/)

  const approved = await proposeImprovement(suggestion, {
    ...base,
    confirm: async () => true,
  })
  assert.equal(approved.approved, true)
  assert.equal(approved.executable, true)
  assert.equal(approved.status, 'approved')
  assert.match(approved.id, /^imp-[0-9a-f]{8}$/)

  const blocked = await proposeImprovement(suggestion, {
    ...base,
    canEdit: false,
    confirm: async () => true,
  })
  assert.equal(blocked.approved, true)
  assert.equal(blocked.executable, false)
  assert.match(blocked.message, /switch to dev mode/)

  const listed = await listImprovements()
  assert.equal(listed.path, path)
  assert.deepEqual(
    listed.items.map((item) => item.status),
    ['approved', 'approved', 'rejected'],
  )

  const completed = await completeImprovement(approved.id, 'verified')
  assert.equal(completed.status, 'implemented')
  assert.equal(completed.already_completed, false)
  const repeated = await completeImprovement(approved.id, 'verified')
  assert.equal(repeated.already_completed, true)
  await assert.rejects(completeImprovement(declined.id), /declined/)

  await assert.rejects(
    proposeImprovement(suggestion, {
      ...base,
      hasUI: false,
      confirm: async () => true,
    }),
    /interactive session/,
  )
})
