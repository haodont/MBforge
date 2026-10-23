/**
 * Covers `createPdfDocumentCache` (../pdfDocumentCache): in-flight promise
 * reuse on cache hits, LRU eviction, and destroy-on-evict of loaded documents.
 */
import { describe, expect, it, vi } from 'vitest'
import { createPdfDocumentCache } from '../pdfDocumentCache'

type FakeDocument = { destroy?: () => unknown }

describe('createPdfDocumentCache', () => {
  it('caches loaded documents with LRU eviction and destroys evicted ones', async () => {
    // Capacity overflow evicts the least recently used document and destroys it.
    const documents = new Map<string, FakeDocument>()
    const getDocument = vi.fn((url: string) => {
      const document = { destroy: vi.fn().mockResolvedValue(undefined) }
      documents.set(url, document)
      return { promise: Promise.resolve(document) }
    })
    const lruCache = createPdfDocumentCache<FakeDocument>(3, getDocument)

    await lruCache.get('one.pdf')
    await lruCache.get('two.pdf')
    await lruCache.get('three.pdf')
    await lruCache.get('one.pdf')
    await lruCache.get('four.pdf')

    expect(documents.get('two.pdf')?.destroy).toHaveBeenCalledOnce()
    expect(documents.get('one.pdf')?.destroy).not.toHaveBeenCalled()
    expect(lruCache.keys()).toEqual(['three.pdf', 'one.pdf', 'four.pdf'])

    // A concurrent second get for the same key reuses the in-flight promise
    // (only one loader call), and the evicted document is destroyed.
    const document = { destroy: vi.fn().mockResolvedValue(undefined) }
    const loadOnce = vi.fn(() => ({ promise: Promise.resolve(document) }))
    const hitCache = createPdfDocumentCache<FakeDocument>(1, loadOnce)

    const first = hitCache.get('same.pdf')
    const second = hitCache.get('same.pdf')
    await hitCache.get('other.pdf')
    await Promise.all([first, second])

    expect(first).toBe(second)
    expect(loadOnce).toHaveBeenCalledTimes(2)
    expect(document.destroy).toHaveBeenCalledOnce()
  })
})
