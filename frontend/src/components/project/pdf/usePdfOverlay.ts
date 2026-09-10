/**
 * Document overlay loader — the single SQL-backed request behind the PDF
 * viewer.
 *
 * One request per document primes both the OCR layout blocks and every page's
 * molecule bboxes, so page turns never refetch. The hook only performs the
 * request and reports progress; the fetched data is handed to the caller,
 * which owns it (the viewer façade keeps it in state and mirrors it into the
 * per-document snapshot).
 */

import { useEffect, useRef, useState } from 'react'
import { getDocumentOverlay } from '@/api/http/pdf'
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
  const [isLoadingOverlay, setIsLoadingOverlay] = useState(false)
  const loadedKeyRef = useRef<string | null>(null)
  const skippedKeyRef = useRef<string | null>(null)

  useEffect(() => {
    if (!libraryRoot || !doc.doc_id || !absDocPath) return
    const docKey = `${libraryRoot}:${doc.doc_id}`
    if (skip) {
      // Warm snapshot: nothing to fetch, but never fetch later for this doc.
      skippedKeyRef.current = docKey
      return
    }
    if (skippedKeyRef.current === docKey || loadedKeyRef.current === docKey) return
    loadedKeyRef.current = docKey

    // No cancellation flag: React StrictMode runs setup → cleanup → setup, and
    // cancelling the first request would leave the second (guarded) run with
    // nothing to show. Late responses are rejected by comparing the doc key.
    setIsLoadingOverlay(true)
    getDocumentOverlay({ libraryRoot, docId: doc.doc_id, path: absDocPath })
      .then(result => {
        if (loadedKeyRef.current !== docKey) return
        const pages = new Map<number, ExtractionResult[]>()
        for (const [pageKey, rows] of Object.entries(result.pages)) {
          const page = Number(pageKey)
          if (!Number.isFinite(page)) continue
          pages.set(page, enrichResults(rows, page))
        }
        onLoaded(result.blocks, pages)
        const hasBlocks = result.blocks.length > 0
        showToast(
          hasBlocks ? `加载 ${result.blocks.length} 个 OCR 块` : OCR_EMPTY_HINT,
          hasBlocks ? 'success' : 'info',
        )
      })
      .catch((e: unknown) => {
        if (loadedKeyRef.current !== docKey) return
        console.error('Failed to load document overlay:', e)
        showToast(`文档覆盖层加载失败：${getUserFacingError(e)}`, 'error')
      })
      .finally(() => {
        if (loadedKeyRef.current === docKey) setIsLoadingOverlay(false)
      })
  }, [absDocPath, doc.doc_id, enrichResults, libraryRoot, onLoaded, skip])

  return { isLoadingOverlay }
}
