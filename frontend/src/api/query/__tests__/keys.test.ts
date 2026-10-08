import { describe, it, expect } from 'vitest'
import { queryKeys } from '../keys'

describe('queryKeys', () => {
  it('produces stable, correctly-shaped keys', () => {
    expect(queryKeys.library.status()).toEqual(['library', 'status'])
    expect(queryKeys.documents.list()).toEqual(['documents', 'list'])
    expect(queryKeys.ingest.queue('/tmp/lib')).toEqual(['ingest', 'queue', '/tmp/lib'])
    expect(queryKeys.molecules.list('/lib')).toEqual(['molecules', 'list', '/lib'])
    expect(queryKeys.notes.list('/r')).toEqual(['notes', '/r'])
    expect(queryKeys.sar.cliffs('/lib', 0.7, 5)).toEqual(['sar', 'cliffs', '/lib', 0.7, 5])
    expect(queryKeys.sar.scaffoldProfile('/lib', 'c1ccccc1')).toEqual([
      'sar',
      'scaffold-profile',
      '/lib',
      'c1ccccc1',
    ])
    expect(queryKeys.sar.matrix([], 'c1ccccc1')).toEqual(['sar', 'matrix', [], 'c1ccccc1'])
  })
})
