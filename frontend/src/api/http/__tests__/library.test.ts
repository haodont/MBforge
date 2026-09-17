import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { cropImageUrl, importDocument } from '../library'

describe('cropImageUrl', () => {
  it('joins rel_path and library_root with a single &', () => {
    const url = cropImageUrl('doc1', 'page_0001_mol_0002.png', 'C:\\MBForge\\lib')
    expect(url).toBe(
      '/api/v1/library/documents/doc1/crop?library_root=C%3A%5CMBForge%5Clib&rel_path=page_0001_mol_0002.png'
    )
    expect(url.split('?').length).toBe(2)
  })

  it('URL-encodes Windows library_root with a trailing backslash', () => {
    const url = cropImageUrl('doc-1', 'crop.png', 'D:\\Users\\某\\lib\\')
    expect(url).toContain('library_root=D%3A%5CUsers%5C%E6%9F%90%5Clib%5C')
    expect(url).toContain('rel_path=crop.png')
  })

  it('URL-encodes rel_path with spaces and non-ASCII characters', () => {
    const url = cropImageUrl('doc1', '图 1.png', 'C:\\lib')
    expect(url).toContain('rel_path=%E5%9B%BE+1.png')
  })

  it('preserves backend namespace prefix when an api base is configured', () => {
    const url = cropImageUrl('doc1', 'crop.png', 'C:\\lib')
    expect(url.startsWith('/api/v1/library/documents/')).toBe(true)
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

  it('sends a multipart request via httpFetch and returns the server response', async () => {
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
  })

  it('does not override the multipart Content-Type header', async () => {
    fetchMock.mockResolvedValueOnce(mockFetchResponse({ success: true }))

    const file = new File(['bytes'], 'test.pdf')
    await importDocument(file)

    const [, init] = fetchMock.mock.calls[0]
    const headers = new Headers(init?.headers)
    expect(headers.get('Content-Type')).toBeNull()
  })

  it('throws when the server responds with non-OK status', async () => {
    fetchMock.mockResolvedValueOnce(mockFetchResponse({ success: false, error: 'upload too large' }, 413))

    const file = new File(['bytes'], 'huge.pdf')
    await expect(importDocument(file)).rejects.toThrow('upload too large')
  })
})
