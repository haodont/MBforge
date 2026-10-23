/**
 * Covers `createLruMap` (../lruMap): capacity-bounded insertion order,
 * MRU promotion on read and the eviction callback contract.
 */
import { describe, expect, it, vi } from 'vitest'
import { createLruMap } from '../lruMap'

describe('createLruMap', () => {
  it('evicts the least recently used entry once capacity is exceeded', () => {
    // Plain insert overflow: the oldest key goes.
    const simple = createLruMap<string, number>(3)
    simple.set('a', 1)
    simple.set('b', 2)
    simple.set('c', 3)
    simple.set('d', 4)
    expect(simple.has('a')).toBe(false)
    expect(simple.keys()).toEqual(['b', 'c', 'd'])

    // A read promotes the touched key back to most-recent, so the untouched
    // key becomes the eviction victim.
    const touched = createLruMap<string, number>(3)
    touched.set('a', 1)
    touched.set('b', 2)
    touched.set('c', 3)
    touched.get('a')
    touched.set('d', 4)
    expect(touched.keys()).toEqual(['c', 'a', 'd'])
    expect(touched.has('b')).toBe(false)

    // Re-setting an existing key must not evict the just-set key.
    const reset = createLruMap<string, number>(2)
    reset.set('a', 1)
    reset.set('b', 2)
    reset.set('a', 11)
    expect(reset.keys()).toEqual(['b', 'a'])

    // Eviction reports the evicted key/value pair to onEvict.
    const onEvict = vi.fn()
    const withCallback = createLruMap<string, { tag: string }>(1, { onEvict })
    withCallback.set('only', { tag: 'first' })
    withCallback.set('other', { tag: 'second' })
    expect(onEvict).toHaveBeenCalledWith('only', { tag: 'first' })
    expect(withCallback.has('only')).toBe(false)
  })
})
