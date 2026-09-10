import { describe, expect, it, vi } from 'vitest'
import { createLruMap } from '../lruMap'

describe('createLruMap', () => {
  it('evicts least recently used key once capacity is exceeded', () => {
    const map = createLruMap<string, number>(3)

    map.set('a', 1)
    map.set('b', 2)
    map.set('c', 3)
    map.set('d', 4)

    expect(map.has('a')).toBe(false)
    expect(map.keys()).toEqual(['b', 'c', 'd'])
  })

  it('promotes a touched key back to most-recent', () => {
    const map = createLruMap<string, number>(3)

    map.set('a', 1)
    map.set('b', 2)
    map.set('c', 3)
    map.get('a')
    map.set('d', 4)

    expect(map.keys()).toEqual(['c', 'a', 'd'])
    expect(map.has('b')).toBe(false)
  })

  it('does not evict the just-set key when it would otherwise overflow', () => {
    const map = createLruMap<string, number>(2)

    map.set('a', 1)
    map.set('b', 2)
    // size would exceed max only because re-set keeps the same key
    map.set('a', 11)

    expect(map.keys()).toEqual(['b', 'a'])
  })

  it('invokes onEvict for the evicted key/value pair', () => {
    const onEvict = vi.fn()
    const map = createLruMap<string, { tag: string }>(1, { onEvict })

    map.set('only', { tag: 'first' })
    map.set('other', { tag: 'second' })

    expect(onEvict).toHaveBeenCalledWith('only', { tag: 'first' })
    expect(map.has('only')).toBe(false)
  })
})