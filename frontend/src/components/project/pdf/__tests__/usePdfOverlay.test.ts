import { describe, it, expect, vi, beforeEach } from 'vitest'
import { StrictMode } from 'react'
import { renderHook, waitFor } from '@testing-library/react'
import type { ExtractionResult } from '@/types'

vi.mock('@/api/http/pdf', () => ({
  getDocumentOverlay: vi.fn(),
}))

vi.mock('@/hooks/useToast', () => ({
  showToast: vi.fn(),
}))

import { getDocumentOverlay } from '@/api/http/pdf'
import type { OcrBlock } from '@/api/http/pdf'
import { usePdfOverlay } from '../usePdfOverlay'

const doc = {
  doc_id: 'doc-1',
  path: 'a.pdf',
  doc_type: 'pdf' as const,
  title: 'A',
}

const enrich = (rows: ExtractionResult[]) => rows

function detection(page: number): ExtractionResult {
  return {
    esmiles: `C-${page}`,
    name: '',
    source: 'image',
    moldet_conf: 0.9,
    bbox_pdf: [10, 10, 50, 50],
    page_idx: page - 1,
    context_text: '',
    mol_img_path: null,
    status: 'pending',
    properties: {},
  }
}

const block: OcrBlock = {
  evidence_id: 'ev-1',
  page: 1,
  block_type: 'text',
  bbox: [1, 2, 3, 4],
  content: 'text',
  index: 0,
  angle: 0,
}

const mockedOverlay = vi.mocked(getDocumentOverlay)

describe('usePdfOverlay — one request per document', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockedOverlay.mockResolvedValue({
      success: true,
      path: '/lib/a.pdf',
      from_cache: true,
      blocks: [block],
      pages: { 1: [detection(1)], 2: [detection(2)] },
      count: 2,
      source: 'source_evidence',
    })
  })

  it('primes blocks and every page bbox from a single request', async () => {
    const onLoaded = vi.fn()
    const { rerender } = renderHook(() =>
      usePdfOverlay({
        doc,
        libraryRoot: '/lib',
        absDocPath: '/lib/a.pdf',
        skip: false,
        enrichResults: enrich,
        onLoaded,
      }),
    )

    await waitFor(() => expect(mockedOverlay).toHaveBeenCalledTimes(1))
    expect(mockedOverlay).toHaveBeenCalledWith({
      libraryRoot: '/lib',
      docId: 'doc-1',
      path: '/lib/a.pdf',
    })
    await waitFor(() => expect(onLoaded).toHaveBeenCalledTimes(1))
    const [blocks, pages] = onLoaded.mock.calls[0] as [
      OcrBlock[],
      Map<number, ExtractionResult[]>,
    ]
    expect(blocks).toEqual([block])
    expect(pages.get(2)?.[0]?.esmiles).toBe('C-2')

    // Page turns and later enrich re-renders must not refetch.
    rerender()
    expect(mockedOverlay).toHaveBeenCalledTimes(1)
  })

  it('still delivers the overlay under React StrictMode double-invoke', async () => {
    const onLoaded = vi.fn()
    renderHook(
      () =>
        usePdfOverlay({
          doc,
          libraryRoot: '/lib',
          absDocPath: '/lib/a.pdf',
          skip: false,
          enrichResults: enrich,
          onLoaded,
        }),
      { wrapper: StrictMode },
    )

    // The request fires once; the second (StrictMode) setup must not swallow
    // the first response and leave the viewer without any box.
    await waitFor(() => expect(onLoaded).toHaveBeenCalledTimes(1))
    const [, pages] = onLoaded.mock.calls[0] as [
      OcrBlock[],
      Map<number, ExtractionResult[]>,
    ]
    expect(pages.get(2)?.[0]?.esmiles).toBe('C-2')
    expect(mockedOverlay).toHaveBeenCalledTimes(1)
  })

  it('skips the request when a warm snapshot already holds the overlay', () => {
    renderHook(() =>
      usePdfOverlay({
        doc,
        libraryRoot: '/lib',
        absDocPath: '/lib/a.pdf',
        skip: true,
        enrichResults: enrich,
        onLoaded: vi.fn(),
      }),
    )

    expect(mockedOverlay).not.toHaveBeenCalled()
  })

  it('does not fetch without a library root', () => {
    renderHook(() =>
      usePdfOverlay({
        doc,
        libraryRoot: '',
        absDocPath: '/lib/a.pdf',
        skip: false,
        enrichResults: enrich,
        onLoaded: vi.fn(),
      }),
    )

    expect(mockedOverlay).not.toHaveBeenCalled()
  })
})
