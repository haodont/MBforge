/**
 * library.ts — `cropImageUrl` / `importDocument` / `exportStructureActivity`.
 *
 * Protects the URL builder that must survive
 * Windows paths / non-ASCII rel_paths without breaking the query string, and
 * the multipart import path, and binary dataset downloads with server errors surfaced.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { cropImageUrl, exportStructureActivity, importDocument } from '../library'

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

describe('exportStructureActivity', () => {
  afterEach(() => {
    vi.useRealTimers()
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
  })

  it('downloads the selected-document archive unchanged and surfaces stale-snapshot errors without downloading', async () => {
    vi.useFakeTimers()
    const archive = new Uint8Array([0x50, 0x4b, 3, 4, 0, 255])
    const fetchMock = vi.fn<typeof fetch>().mockResolvedValueOnce(new Response(archive, {
      headers: { 'Content-Type': 'application/zip' },
    }))
    vi.stubGlobal('fetch', fetchMock)
    const createObjectURL = vi.fn<(blob: Blob) => string>().mockReturnValue('blob:archive')
    const revokeObjectURL = vi.fn()
    vi.stubGlobal('URL', class extends URL {
      static createObjectURL = createObjectURL
      static revokeObjectURL = revokeObjectURL
    })
    const downloaded: string[] = []
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (this: HTMLAnchorElement) {
      downloaded.push(this.download)
    })

    await exportStructureActivity(['doc-a', 'doc-b'], 'C:\\library')

    expect(fetchMock.mock.calls[0][0]).toBe('/api/v1/activities/export')
    expect(JSON.parse(fetchMock.mock.calls[0][1]?.body as string)).toEqual({
      doc_ids: ['doc-a', 'doc-b'], library_root: 'C:\\library',
    })
    const delivered = createObjectURL.mock.calls[0]
    expect(new Uint8Array(await delivered[0].arrayBuffer())).toEqual(archive)
    expect(downloaded).toEqual(['structure-activity.zip'])
    expect(document.querySelector('a[download]')).toBeNull()
    await vi.runAllTimersAsync()
    expect(revokeObjectURL).toHaveBeenCalledWith('blob:archive')

    fetchMock.mockResolvedValueOnce(new Response(JSON.stringify({
      error: 'Evidence changed; rerun patent analysis', error_code: 'conflict',
    }), { status: 409 }))
    await expect(exportStructureActivity(['doc-a'], 'C:\\library'))
      .rejects.toThrow('Evidence changed; rerun patent analysis')
    expect(downloaded).toHaveLength(1)
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
