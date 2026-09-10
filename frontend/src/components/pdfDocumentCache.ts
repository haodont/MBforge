import { createLruMap } from './lruMap'

export interface PdfDocumentCache<T> {
  get: (url: string) => Promise<T>
  keys: () => string[]
}

export function createPdfDocumentCache<T extends { destroy?: () => unknown }>(
  maxSize: number,
  load: (url: string) => { promise: Promise<T> },
): PdfDocumentCache<T> {
  const cache = createLruMap<string, Promise<T>>(maxSize, {
    onEvict: (_key, promise) => {
      void promise
        .then(doc => doc.destroy?.())
        .catch(() => undefined)
    },
  })

  function get(url: string): Promise<T> {
    const existing = cache.get(url)
    if (existing) return existing
    const promise = load(url).promise
    cache.set(url, promise)
    return promise
  }

  return { get, keys: () => cache.keys() }
}