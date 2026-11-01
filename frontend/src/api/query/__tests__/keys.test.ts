/**
 * keys.ts — `queryKeys` (covered object at top).
 *
 * TanStack Query keys are the cache identity: a changed shape silently splits
 * caches and breaks invalidation, so the exact tuples are pinned here.
 */

import { describe, it, expect } from 'vitest'
import { queryKeys } from '../keys'

describe('queryKeys', () => {
  it('produces stable, correctly-shaped keys', () => {
    const cases: Array<[readonly unknown[], unknown, string]> = [
      [queryKeys.library.status(), ['library', 'status'], 'library.status'],
      [queryKeys.documents.list(), ['documents', 'list'], 'documents.list'],
      [queryKeys.ingest.queue('/tmp/lib'), ['ingest', 'queue', '/tmp/lib'], 'ingest.queue'],
      [queryKeys.molecules.list('/lib'), ['molecules', 'list', '/lib'], 'molecules.list'],
      [queryKeys.notes.list('/r'), ['notes', '/r'], 'notes.list'],
    ]
    for (const [actual, expected, name] of cases) {
      expect(actual, name).toEqual(expected)
    }
  })
})
