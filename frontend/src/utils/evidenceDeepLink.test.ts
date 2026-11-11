// @tested-functions parseEvidenceDeepLink
import { expect, it } from 'vitest'
import { parseEvidenceDeepLink } from './evidenceDeepLink'

it('parses a citation deep link and drops malformed page/bbox', () => {
  expect(parseEvidenceDeepLink('?doc=abc&page=5&bbox=1,2,3,4&evidence=ev-1')).toEqual({
    docId: 'abc',
    page: 5,
    bbox: [1, 2, 3, 4],
    evidenceId: 'ev-1',
  })
  expect(parseEvidenceDeepLink('?doc=abc&page=0&bbox=1,2,3')).toEqual({
    docId: 'abc',
    page: undefined,
    bbox: undefined,
    evidenceId: undefined,
  })
  expect(parseEvidenceDeepLink('?page=5')).toBeNull()
})