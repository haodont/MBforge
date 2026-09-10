import { describe, expect, it, vi } from 'vitest'
import { createPdfDocumentCache } from '../pdfDocumentCache'

type FakeDocument = { destroy?: () => unknown }

describe('createPdfDocumentCache', () => {
  it('evicts least recently used document after capacity is exceeded', async () => {
    const documents = new Map<string, FakeDocument>()
    const getDocument = vi.fn((url: string) => {
      const document = { destroy: vi.fn().mockResolvedValue(undefined) }
      documents.set(url, document)
      return { promise: Promise.resolve(document) }
    })
    const cache = createPdfDocumentCache<FakeDocument>(3, getDocument)

    await cache.get('one.pdf')
    await cache.get('two.pdf')
    await cache.get('three.pdf')
    await cache.get('one.pdf')
    await cache.get('four.pdf')

    expect(documents.get('two.pdf')?.destroy).toHaveBeenCalledOnce()
    expect(documents.get('one.pdf')?.destroy).not.toHaveBeenCalled()
    expect(cache.keys()).toEqual(['three.pdf', 'one.pdf', 'four.pdf'])
  })

  it('reuses promise on cache hit and destroys evicted document', async () => {
    const document = { destroy: vi.fn().mockResolvedValue(undefined) }
    const getDocument = vi.fn(() => ({ promise: Promise.resolve(document) }))
    const cache = createPdfDocumentCache<FakeDocument>(1, getDocument)

    const first = cache.get('same.pdf')
    const second = cache.get('same.pdf')
    await cache.get('other.pdf')
    await Promise.all([first, second])

    expect(first).toBe(second)
    expect(getDocument).toHaveBeenCalledTimes(2)
    expect(document.destroy).toHaveBeenCalledOnce()
  })
})
