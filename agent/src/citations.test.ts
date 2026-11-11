// @tested-functions harvestEvidence, rememberEvidence, linkifyCitations, evidenceDeepLink
import assert from 'node:assert/strict'
import test from 'node:test'

import {
  clearEvidence,
  harvestEvidence,
  linkifyCitations,
  rememberEvidence,
} from './citations.js'

test('citations resolve to frontend deep links from both evidence tools; unknown markers stay literal', () => {
  clearEvidence()
  const search = harvestEvidence(
    'search_evidence',
    {},
    { items: [{ evidence_id: 'ev-s', doc_id: 'doc-abc', page: 2, kind: 'text', snippet: 's' }] },
  )
  const list = harvestEvidence(
    'list_evidence',
    { doc_id: 'doc-xyz' },
    { items: [{ evidence_id: 'ev-l', page: 5, bbox: [1, 2, 3, 4], kind: 'text', raw_text: 'x' }] },
  )
  const verified = harvestEvidence(
    'verify_structures',
    { doc_id: 'doc-xyz' },
    { items: [{ evidence_id: 'ev-v', page: 62, bbox: [10, 20, 30, 40], formula: 'C13H19N5' }] },
  )
  for (const location of [...search, ...list, ...verified]) rememberEvidence(location)

  const out = linkifyCitations('A [[ev:ev-s]] B [[ev:ev-l]] C [[ev:ev-v]] D [[ev:missing]].')

  assert.ok(out.includes('[来源·p.2]('), out)
  assert.ok(out.includes('doc=doc-abc'), out)
  assert.ok(out.includes('[来源·p.5]('), out)
  assert.ok(out.includes('doc=doc-xyz'), out)
  assert.ok(out.includes('bbox=1%2C2%2C3%2C4'), out)
  assert.ok(out.includes('[来源·p.62]('), out)
  assert.ok(out.includes('bbox=10%2C20%2C30%2C40'), out)
  assert.ok(out.includes('[[ev:missing]]'), out)
})