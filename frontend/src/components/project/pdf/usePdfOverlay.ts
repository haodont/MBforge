/**
 * Document overlay loader — the single SQL-backed request behind the PDF
 * viewer.
 *
 * One request per document primes both the OCR layout blocks and every page's
 * molecule bboxes, so page turns never refetch. The request itself lives in
 * the query layer (``useDocumentOverlay``); this hook only reports progress and
 * hands the fetched data to the caller, which owns it (the viewer façade keeps
 * it in state and mirrors it into the per-document snapshot).
 */

import { useEffect, useRef } from 'react'
import { useDocumentOverlay } from '@/api/query/hooks'
import { showToast } from '@/hooks/useToast'
import { getUserFacingError } from '@/utils/errors'
import type { DocumentEntry, ExtractionResult } from '@/types'
import type { OcrBlock } from '@/api/http/pdf'

/** Empty-state hint for the OCR panel: every document runs through OCR now,
 * so there is no longer a parser-specific message. */
export const OCR_EMPTY_HINT = '未找到 OCR 布局数据'

export interface UsePdfOverlayArgs {
  doc: DocumentEntry
  libraryRoot: string
  absDocPath: string
  /** Skip the request when a warm snapshot already holds the overlay. */
  skip: boolean
  enrichResults: (results: ExtractionResult[], pageNum: number) => ExtractionResult[]
  onLoaded: (blocks: OcrBlock[], pages: Map<number, ExtractionResult[]>) => void
}

export function usePdfOverlay(args: UsePdfOverlayArgs): { isLoadingOverlay: boolean } {
  const { doc, libraryRoot, absDocPath, skip, enrichResults, onLoaded } = args
  const docKey = `${libraryRoot}:${doc.doc_id}`

  const { data, error, isLoading } = useDocumentOverlay({
    libraryRoot,
    docId: doc.doc_id,
    path: absDocPath,
    enabled: !skip,
  })

  // Deliver each document's overlay exactly once, so later re-renders (page
  // turns, enrich re-renders, a cached refetch) never re-run ``onLoaded``.
  const deliveredKeyRef = useRef<string | null>(null)

  useEffect(() => {
    if (!data) return
    if (deliveredKeyRef.current === docKey) return
    deliveredKeyRef.current = docKey

    const pages = new Map<number, ExtractionResult[]>()
    for (const [pageKey, rows] of Object.entries(data.pages)) {
      const page = Number(pageKey)
      if (!Number.isFinite(page)) continue
      pages.set(page, enrichResults(rows, page))
    }
    onLoaded(data.blocks, pages)
    const hasBlocks = data.blocks.length > 0
    showToast(
      hasBlocks ? `加载 ${data.blocks.length} 个 OCR 块` : OCR_EMPTY_HINT,
      hasBlocks ? 'success' : 'info',
    )
  }, [data, docKey, enrichResults, onLoaded])

  useEffect(() => {
    if (!error) return
    console.error('Failed to load document overlay:', error)
    showToast(`文档覆盖层加载失败：${getUserFacingError(error)}`, 'error')
  }, [error])

  return { isLoadingOverlay: isLoading }
}
