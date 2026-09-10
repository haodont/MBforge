/**
 * Generic LRU map. Insertion order tracks most-recently-used.
 *
 * - `set` re-inserts existing keys, so the just-set key is the MRU.
 * - When the map exceeds `maxSize`, the oldest key is evicted and the
 *   optional `onEvict` callback fires with the evicted key/value pair.
 * - Touching via `get` also promotes the key to MRU; pass
 *   `touchOnGet: false` to keep reads out of the ordering.
 */

export interface LruMapOptions<V> {
  onEvict?: (key: string, value: V) => void
  touchOnGet?: boolean
}

export interface LruMap<K extends string, V> {
  get: (key: K) => V | undefined
  set: (key: K, value: V) => void
  delete: (key: K) => boolean
  has: (key: K) => boolean
  keys: () => K[]
  size: () => number
}

export function createLruMap<K extends string = string, V = unknown>(
  maxSize: number,
  options: LruMapOptions<V> = {},
): LruMap<K, V> {
  const entries = new Map<K, V>()
  const touchOnGet = options.touchOnGet !== false

  function evictOldest(except?: K): void {
    if (entries.size <= maxSize) return
    const oldest = entries.keys().next().value
    if (oldest === undefined || oldest === except) return
    const value = entries.get(oldest)
    entries.delete(oldest)
    if (value !== undefined) options.onEvict?.(oldest, value)
  }

  return {
    get(key) {
      if (!entries.has(key)) return undefined
      if (touchOnGet) {
        const value = entries.get(key) as V
        entries.delete(key)
        entries.set(key, value)
      }
      return entries.get(key)
    },
    set(key, value) {
      if (entries.has(key)) entries.delete(key)
      entries.set(key, value)
      evictOldest(key)
    },
    delete(key) {
      return entries.delete(key)
    },
    has(key) {
      return entries.has(key)
    },
    keys() {
      return [...entries.keys()]
    },
    size() {
      return entries.size
    },
  }
}