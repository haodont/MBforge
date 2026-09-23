/**
 * PDF viewer OCR — owns the OCR panel toggle and the detection flows:
 *
 * - Layout blocks are seeded by the document overlay request
 *   (``usePdfOverlay``); this hook no longer fetches them.
 * - Recognition run: handleRecognizePage re-runs the model on the current page
 *   and persists results (savePageDetections).
 * - Clear cache: handleClearDetectionCache wipes the per-document cache and
 *   resets detection state.
 */

import { useCallback, useState } from 'react'
import {
  extractPdfMolecules,
  savePageDetections,
  clearDetectionCacheForDoc,
} from '@/api/http/detection_cache'
import { showToast } from '@/hooks/useToast'
import { getUserFacingError } from '@/utils/errors'
import type { DocumentEntry, ExtractionResult } from '@/types'

export interface UsePdfOcrArgs {
  doc: DocumentEntry
  libraryRoot: string
  initialShowOcrPanel?: boolean
  // Navigation-owned dependencies the recognition run needs.
  currentPage: number
  currentPageDataUrl: string | null
  pageInfo: { pageNumber: number } | null
  // Detection-owned state the recognition flow mutates.
  setPageDetections: React.Dispatch<React.SetStateAction<Map<number, ExtractionResult[]>>>
  setIsDetecting: React.Dispatch<React.SetStateAction<boolean>>
  setSelectedDetection: React.Dispatch<React.SetStateAction<number | null>>
  enrichResults: (results: ExtractionResult[], pageNum: number) => ExtractionResult[]
}

export interface UsePdfOcrResult {
  showOcrPanel: boolean
  setShowOcrPanel: React.Dispatch<React.SetStateAction<boolean>>
  selectedOcrIndex: number | null
  setSelectedOcrIndex: React.Dispatch<React.SetStateAction<number | null>>
  handleRecognizePage: () => Promise<void>
  handleClearDetectionCache: () => Promise<void>
}

export function usePdfOcr(args: UsePdfOcrArgs): UsePdfOcrResult {
  const {
    doc, libraryRoot,
    initialShowOcrPanel,
    currentPage, currentPageDataUrl, pageInfo,
    setPageDetections,
    setIsDetecting, setSelectedDetection,
    enrichResults,
  } = args

  const [showOcrPanel, setShowOcrPanel] = useState(initialShowOcrPanel ?? false)
  const [selectedOcrIndex, setSelectedOcrIndex] = useState<number | null>(null)

  const handleRecognizePage = useCallback(async () => {
    if (!currentPageDataUrl || !pageInfo) {
      showToast('页面尚未渲染完成，请稍候', 'info')
      return
    }
    setIsDetecting(true)
    setSelectedDetection(null)
    try {
      const results = await extractPdfMolecules({
        libraryRoot,
        docId: doc.doc_id,
        page: currentPage,
      })
      const enriched = enrichResults(results, currentPage)
      try {
        // 存 0-based 页码，与 pipeline persist 写入的行同语义。
        await savePageDetections(libraryRoot, doc.doc_id, currentPage - 1, enriched)
      } catch (saveError) {
        console.warn('[PdfViewer] Failed to save recognized detections:', saveError)
      }
      setPageDetections(prev => { const next = new Map(prev); next.set(currentPage, enriched); return next })
      showToast(
        results.length > 0 ? `识别到 ${results.length} 个分子` : '未识别到分子',
        results.length > 0 ? 'success' : 'info',
      )
    } catch (e) {
      console.error('Recognition failed:', e)
      showToast('识别失败: ' + getUserFacingError(e), 'error')
    } finally { setIsDetecting(false) }
  }, [currentPageDataUrl, pageInfo, currentPage, libraryRoot, doc.doc_id, enrichResults, setIsDetecting, setPageDetections, setSelectedDetection])

  const handleClearDetectionCache = useCallback(async () => {
    if (!libraryRoot) return
    setIsDetecting(true)
    try {
      await clearDetectionCacheForDoc(libraryRoot, doc.doc_id)
      setPageDetections(new Map())
      setSelectedDetection(null)
      showToast('分子识别缓存已清除', 'success')
    } catch (e) {
      console.error('Failed to clear detection cache:', e)
      showToast('清除缓存失败: ' + getUserFacingError(e), 'error')
    } finally { setIsDetecting(false) }
  }, [libraryRoot, doc.doc_id, setIsDetecting, setPageDetections, setSelectedDetection])

  return {
    showOcrPanel, setShowOcrPanel,
    selectedOcrIndex, setSelectedOcrIndex,
    handleRecognizePage,
    handleClearDetectionCache,
  }
}
