import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('../_utils', () => ({
  httpPost: vi.fn(),
  invokeWithError: vi.fn((fn: () => Promise<unknown>) => fn()),
}))

import { httpPost } from '../_utils'
import { getDocumentOverlay } from '../pdf'

const mockHttpPost = vi.mocked(httpPost)

describe('pdf API — document overlay', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('posts path and doc_id to /api/v1/pdf/document-overlay', async () => {
    mockHttpPost.mockResolvedValue({
      success: true,
      path: '/p.pdf',
      from_cache: true,
      blocks: [],
      pages: {},
      count: 0,
      source: 'empty',
    })
    const result = await getDocumentOverlay({
      libraryRoot: '/lib',
      docId: 'doc-1',
      path: '/p.pdf',
    })
    expect(httpPost).toHaveBeenCalledWith('/api/v1/pdf/document-overlay', {
      library_root: '/lib',
      doc_id: 'doc-1',
      path: '/p.pdf',
    })
    expect(result.blocks).toEqual([])
    expect(result.pages).toEqual({})
  })
})
