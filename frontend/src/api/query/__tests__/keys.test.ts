import { describe, it, expect } from 'vitest'
import { queryKeys } from '../keys'

describe('queryKeys', () => {
  it('produces stable, correctly-shaped keys', () => {
    expect(queryKeys.library.status()).toEqual(['library', 'status'])
    expect(queryKeys.documents.list('col-1')).toEqual(['documents', { collectionId: 'col-1' }])
    expect(queryKeys.ingest.queue('/tmp/lib')).toEqual(['ingest', 'queue', '/tmp/lib'])
    expect(queryKeys.molecules.list('/lib')).toEqual(['molecules', 'list', '/lib'])
    expect(queryKeys.notes.list('/r')).toEqual(['notes', '/r'])
  })
})
