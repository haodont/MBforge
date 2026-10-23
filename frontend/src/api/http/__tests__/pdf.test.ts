/**
 * pdf.ts — `getDocumentOverlay` (covered function at top).
 *
 * Single-item file kept for one contract: the route body must use the
 * backend's snake_case keys while the wrapper exposes camelCase params.
 */

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

  it('maps camelCase params onto the snake_case overlay payload', async () => {
    mockHttpPost.mockResolvedValue({
      success: true,
      path: '/p.pdf',
      from_cache: true,
      blocks: [],
      pages: {},
      count: 0,
      source: 'empty',
    })
    await getDocumentOverlay({ libraryRoot: '/lib', docId: 'doc-1', path: '/p.pdf' })
    expect(httpPost).toHaveBeenCalledWith('/api/v1/pdf/document-overlay', {
      library_root: '/lib',
      doc_id: 'doc-1',
      path: '/p.pdf',
    })
  })
})
