/**
 * PDF viewer deep-link lifecycle.
 *
 * Jump to an ``initialPage``, scroll to an ``initialBbox`` once the page is
 * rendered, select an ``initialEvidenceId``, and drop the per-page selection
 * (evidence / inline edit / OCR overlay) whenever the visible page changes.
 */

import { useEffect, useRef } from 'react'
import type { Dispatch, SetStateAction } from 'react'
import type { ExtractionResult } from '@/types'
import type { PageRenderInfo } from './usePdfNavigation'

export interface UsePdfDeepLinkArgs {
  initialPage?: number
  initialBbox?: [number, number, number, number]
  initialEvidenceId?: string
  currentPage: number
  setCurrentPage: Dispatch<SetStateAction<number>>
  pageInfo: PageRenderInfo | null
  scrollToDetection: (detection: ExtractionResult) => void
  setSelectedEvidenceId: Dispatch<SetStateAction<string | null>>
  setSelectedOcrIndex: Dispatch<SetStateAction<number | null>>
  setEditingDetectionIndex: Dispatch<SetStateAction<number | null>>
}

export function usePdfDeepLink({
  initialPage,
  initialBbox,
  initialEvidenceId,
  currentPage,
  setCurrentPage,
  pageInfo,
  scrollToDetection,
  setSelectedEvidenceId,
  setSelectedOcrIndex,
  setEditingDetectionIndex,
}: UsePdfDeepLinkArgs): void {
  // Guards re-scrolling to the same deep-linked bbox across renders.
  const deepLinkKeyRef = useRef<string | null>(null)

  // Any page change drops the current evidence / inline-edit / OCR selection.
  useEffect(() => {
    setSelectedEvidenceId(null)
    setSelectedOcrIndex(null)
    setEditingDetectionIndex(null)
  }, [currentPage, setSelectedEvidenceId, setSelectedOcrIndex, setEditingDetectionIndex])

  useEffect(() => {
    if (!initialPage) return
    if (currentPage !== initialPage) {
      setCurrentPage(initialPage)
      return
    }
    if (!initialBbox || !pageInfo) return
    const key = `${initialPage}:${initialBbox.join(',')}`
    if (deepLinkKeyRef.current === key) return
    deepLinkKeyRef.current = key
    scrollToDetection({
      esmiles: '',
      name: '',
      source: 'manual',
      moldet_conf: 1,
      bbox_pdf: initialBbox,
      page_idx: initialPage - 1,
      context_text: '',
      mol_img_path: null,
      status: 'confirmed',
      properties: {},
    })
  }, [initialBbox, initialPage, currentPage, pageInfo, scrollToDetection, setCurrentPage])

  useEffect(() => {
    if (initialEvidenceId && initialPage && currentPage === initialPage) {
      setSelectedEvidenceId(initialEvidenceId)
    }
  }, [initialEvidenceId, initialPage, currentPage, setSelectedEvidenceId])
}
