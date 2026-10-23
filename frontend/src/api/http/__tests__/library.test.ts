/**
 * library.ts — `cropImageUrl` / `importDocument` (covered functions at top).
 *
 * Protects two non-trivial contracts: the URL builder that must survive
 * Windows paths / non-ASCII rel_paths without breaking the query string, and
 * the multipart import path (no Content-Type override, server errors surfaced).
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { cropImageUrl, importDocument } from '../library'

describe('cropImageUrl', () => {
  it('encodes Windows library roots and non-ASCII rel_paths into one query string', () => {
    const url = cropImageUrl('doc1', 'page_0001_mol_0002.png', 'C:\\MBForge\\lib')
    expect(url).toBe(
      '/api/v1/library/documents/doc1/crop?library_root=C%3A%5CMBForge%5Clib&rel_path=page_0001_mol_0002.png'
    )
    expect(url.split('?').length).toBe(2)
    // Trailing backslash and CJK path segments must round-trip through encoding.
    expect(cropImageUrl('doc-1', 'crop.png', 'D:\\Users\\某\\lib\\'))
      .toContain('library_root=D%3A%5CUsers%5C%E6%9F%90%5Clib%5C')
    expect(cropImageUrl('doc1', '图 1.png', 'C:\\lib')).toContain('rel_path=%E5%9B%BE+1.png')
    // The backend namespace prefix is preserved when an API base is configured.
    expect(cropImageUrl('doc1', 'crop.png', 'C:\\lib').startsWith('/api/v1/library/documents/')).toBe(true)
  })
})

describe('importDocument', () => {
  const originalFetch = globalThis.fetch
  const fetchMock = vi.fn<typeof globalThis.fetch>()

  function mockFetchResponse(body: unknown, status = 200): Response {
    return new Response(JSON.stringify(body), {
      status,
      statusText: status === 200 ? 'OK' : 'Error',
      headers: { 'Content-Type': 'application/json' },
    })
  }

  beforeEach(() => {
    fetchMock.mockReset()
    globalThis.fetch = fetchMock
  })
  afterEach(() => {
    globalThis.fetch = originalFetch
  })

  it('posts multipart FormData without overriding Content-Type and surfaces server errors', async () => {
    const document = {
      doc_id: 'doc-1',
      title: 'Test',
      file_name: 'test.pdf',
      page_count: 1,
      status: 'ready',
      created_at: '2026-07-13T00:00:00Z',
    }
    fetchMock.mockResolvedValueOnce(mockFetchResponse({ success: true, document }))

    const file = new File(['bytes'], 'test.pdf', { type: 'application/pdf' })
    const result = await importDocument(file, 'My Title')

    expect(result.success).toBe(true)
    expect(result.document).toEqual(document)

    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe('/api/v1/library/import')
    expect(init?.method).toBe('POST')
    expect(init?.body).toBeInstanceOf(FormData)
    expect(new Headers(init?.headers).get('Content-Type')).toBeNull()

    fetchMock.mockResolvedValueOnce(mockFetchResponse({ success: false, error: 'upload too large' }, 413))
    await expect(importDocument(new File(['bytes'], 'huge.pdf'))).rejects.toThrow('upload too large')
  })
})
