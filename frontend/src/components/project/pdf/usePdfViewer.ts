/**
 * PDF viewer hook — thin façade composing four focused hooks:
 *
 * - usePdfNavigation — page index, zoom, scroll-to-detection, keyboard/wheel,
 *                      page-render state (pageInfo, currentPageDataUrl, text
 *                      items, PDF URL/scroll container, derived UI overlay).
 * - usePdfOverlay   — the single SQL-backed request that seeds both the OCR
 *                      layout blocks and every page's molecule bboxes.
 * - usePdfDetections — detection map behaviour, save flow, and the
 *                      ``selectedDetection`` overlay state cross-cut across
 *                      detect/recognize/keyboard/wheel/jump.
 * - usePdfOcr        — OCR panel toggle, recognition run, cache clearing.
 *
 * The façade owns ``confidenceThreshold``, the overlay data (``ocrBlocks`` /
 * ``pageDetections``), snapshot persistence (spans every sub-hook), and the
 * keyboard/wheel/jump wrappers that drop the selected overlay on page change.
 * Callers continue to destructure the same single object.
 */

import { useCallback, useEffect, useState } from 'react'
import type { ExtractionResult } from '@/types'
import type { OcrBlock } from '@/api/http/pdf'
import { usePdfNavigation } from './usePdfNavigation'
import { usePdfDetections } from './usePdfDetections'
import { usePdfOcr } from './usePdfOcr'
import { usePdfOverlay } from './usePdfOverlay'
import { viewerSnapshots } from './viewerSnapshots'

export { clearViewerSnapshot } from './usePdfDetections'

export function usePdfViewer(
  doc: import('@/types').DocumentEntry,
  libraryRoot: string,
  viewerKey = doc.doc_id,
  initialPage?: number,
) {
  const saved = viewerSnapshots.get(viewerKey)

  // Confidence threshold — UI filter for visible detections. Owned by the
  // façade because no other hook consults or mutates it.
  const [confidenceThreshold, setConfidenceThreshold] = useState(0.3)

  // Overlay data — seeded from the snapshot and refreshed by the single
  // document overlay request.
  const [ocrBlocks, setOcrBlocks] = useState<OcrBlock[]>(saved?.ocrBlocks ?? [])
  const [pageDetections, setPageDetections] = useState<Map<number, ExtractionResult[]>>(
    () => new Map(saved?.pageDetections ?? []),
  )

  const navigation = usePdfNavigation({
    doc,
    libraryRoot,
    initialPage,
    initialSnapshot: saved
      ? {
          currentPage: saved.currentPage,
          pdfScale: saved.pdfScale,
          showTextLayer: saved.showTextLayer,
          showTextPanel: saved.showTextPanel,
        }
      : undefined,
  })

  const handleOverlayLoaded = useCallback(
    (blocks: OcrBlock[], pages: Map<number, ExtractionResult[]>) => {
      setOcrBlocks(blocks)
      setPageDetections(prev => {
        const next = new Map(prev)
        for (const [page, rows] of pages) next.set(page, rows)
        return next
      })
    },
    [],
  )

  const { isLoadingOverlay } = usePdfOverlay({
    doc,
    libraryRoot,
    absDocPath: navigation.absDocPath,
    // A warm snapshot already carries the overlay — skip the request.
    skip: (saved?.ocrBlocks.length ?? 0) > 0
      && saved?.ocrBlocks.every(block => Boolean(block.evidence_id)) === true,
    enrichResults: navigation.enrichResults,
    onLoaded: handleOverlayLoaded,
  })

  const detections = usePdfDetections({
    doc,
    libraryRoot,
    viewerKey,
    currentPage: navigation.currentPage,
    currentPageDataUrl: navigation.currentPageDataUrl,
    pageInfo: navigation.pageInfo,
    pageTextItems: navigation.pageTextItems,
    enrichResults: navigation.enrichResults,
    pageDetections,
    setPageDetections,
  })

  const ocr = usePdfOcr({
    doc,
    libraryRoot,
    initialShowOcrPanel: saved?.showOcrPanel,
    currentPage: navigation.currentPage,
    currentPageDataUrl: navigation.currentPageDataUrl,
    pageInfo: navigation.pageInfo,
    setPageDetections,
    setIsDetecting: detections.setIsDetecting,
    setSelectedDetection: detections.setSelectedDetection,
    enrichResults: navigation.enrichResults,
  })

  // Snapshot persistence — mirror every persisted UI field + the detection
  // map into a small LRU keyed by viewerKey so reopening a document restores
  // its scroll position, zoom, panels, and detections.
  useEffect(() => {
    viewerSnapshots.set(viewerKey, {
      currentPage: navigation.currentPage,
      pdfScale: navigation.pdfScale,
      showTextLayer: navigation.showTextLayer,
      showTextPanel: navigation.showTextPanel,
      showOcrPanel: ocr.showOcrPanel,
      selectedDetection: detections.selectedDetection,
      pageDetections: Array.from(pageDetections.entries()),
      ocrBlocks,
    })
  }, [
    viewerKey,
    navigation.currentPage,
    navigation.pdfScale,
    navigation.showTextLayer,
    navigation.showTextPanel,
    ocr.showOcrPanel,
    ocrBlocks,
    detections.selectedDetection,
    pageDetections,
  ])

  // Wrap the navigation handlers that change the current page so they also
  // clear the selected detection. The original hook had this inline; lifted
  // to the façade so neither sub-hook owns the cross-cutting state.
  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLDivElement>) => {
      navigation.handleKeyDown(e)
      detections.setSelectedDetection(null)
    },
    [navigation, detections],
  )
  const handleWheel = useCallback(
    (e: React.WheelEvent<HTMLDivElement>) => {
      navigation.handleWheel(e)
      detections.setSelectedDetection(null)
    },
    [navigation, detections],
  )
  const handleJumpToPage = useCallback(() => {
    const before = navigation.currentPage
    const after = navigation.handleJumpToPage()
    if (after !== before) detections.setSelectedDetection(null)
  }, [navigation, detections])

  const currentDetections = pageDetections.get(navigation.currentPage) || []

  return {
    // confidence threshold
    confidenceThreshold, setConfidenceThreshold,
    // navigation state
    currentPage: navigation.currentPage, setCurrentPage: navigation.setCurrentPage,
    pdfScale: navigation.pdfScale, setPdfScale: navigation.setPdfScale,
    pdfPageCount: navigation.pdfPageCount,
    showTextLayer: navigation.showTextLayer, setShowTextLayer: navigation.setShowTextLayer,
    showTextPanel: navigation.showTextPanel, setShowTextPanel: navigation.setShowTextPanel,
    pageJumpInput: navigation.pageJumpInput, setPageJumpInput: navigation.setPageJumpInput,
    // scroll container / page-render state
    pdfUrl: navigation.pdfUrl, pdfLoading: navigation.pdfLoading, pdfScrollRef: navigation.pdfScrollRef,
    pageInfo: navigation.pageInfo, pageInfoRef: navigation.pageInfoRef,
    currentPageDataUrl: navigation.currentPageDataUrl,
    pageTextItems: navigation.pageTextItems,
    // OCR
    ocrBlocks, setOcrBlocks,
    showOcrPanel: ocr.showOcrPanel, setShowOcrPanel: ocr.setShowOcrPanel,
    selectedOcrIndex: ocr.selectedOcrIndex, setSelectedOcrIndex: ocr.setSelectedOcrIndex,
    isLoadingOcr: isLoadingOverlay,
    // detections
    pageDetections, setPageDetections,
    isDetecting: detections.isDetecting,
    selectedDetection: detections.selectedDetection, setSelectedDetection: detections.setSelectedDetection,
    // derived
    currentDetections, currentTextItems: navigation.currentTextItems,
    currentTextTotal: navigation.currentTextTotal,
    hasTextLayer: navigation.hasTextLayer, canDetect: navigation.canDetect,
    // handlers
    handleDetectPage: detections.handleDetectPage,
    handleRecognizePage: ocr.handleRecognizePage,
    handleClearDetectionCache: ocr.handleClearDetectionCache,
    handleSaveMolecule: detections.handleSaveMolecule,
    handlePageRendered: navigation.handlePageRendered,
    handleImageReady: navigation.handleImageReady,
    handlePageCount: navigation.handlePageCount,
    handleTextContent: navigation.handleTextContent,
    handleZoomIn: navigation.handleZoomIn,
    handleZoomOut: navigation.handleZoomOut,
    handleZoomReset: navigation.handleZoomReset,
    handleJumpToPage,
    handleKeyDown,
    handleWheel,
    scrollToDetection: navigation.scrollToDetection,
  }
}

// Re-export the detection type for any callers that historically pulled it
// from this module.
export type { ExtractionResult }
