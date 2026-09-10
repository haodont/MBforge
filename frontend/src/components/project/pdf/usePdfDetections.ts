/**
 * PDF viewer detection cache — owns the per-page detection map's behaviour
 * (recognition save flow and bookkeeping) and the ``selectedDetection``
 * overlay state cross-cut across detect/recognize/keyboard/wheel/jump.
 *
 * The map itself is owned by the viewer façade and seeded by the single
 * document overlay request (``usePdfOverlay``); this hook mutates it through
 * the state pair it receives as props.
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import { extractPdfMolecules, savePageDetections } from '@/api/http/detection_cache'
import { updateMoleculeEvidence } from '@/api/http/library'
import { showToast } from '@/hooks/useToast'
import { getUserFacingError } from '@/utils/errors'
import type { DocumentEntry, ExtractionResult } from '@/types'
import type { PageRenderInfo } from './usePdfNavigation'
import type { TextItem } from '@/utils/roiText'
import { viewerSnapshots } from './viewerSnapshots'

export function clearViewerSnapshot(viewerKey: string): void {
  viewerSnapshots.delete(viewerKey)
}

export interface UsePdfDetectionsArgs {
  doc: DocumentEntry
  libraryRoot: string
  viewerKey: string
  /** Navigation-owned primitive state. */
  currentPage: number
  currentPageDataUrl: string | null
  pageInfo: PageRenderInfo | null
  pageTextItems: Map<number, TextItem[]>
  enrichResults: (results: ExtractionResult[], pageNum: number) => ExtractionResult[]
  /** Façade-owned detection map, seeded by the document overlay request. */
  pageDetections: Map<number, ExtractionResult[]>
  setPageDetections: React.Dispatch<React.SetStateAction<Map<number, ExtractionResult[]>>>
}

export interface UsePdfDetectionsResult {
  pageDetections: Map<number, ExtractionResult[]>
  setPageDetections: React.Dispatch<React.SetStateAction<Map<number, ExtractionResult[]>>>
  isDetecting: boolean
  setIsDetecting: React.Dispatch<React.SetStateAction<boolean>>
  selectedDetection: number | null
  setSelectedDetection: React.Dispatch<React.SetStateAction<number | null>>
  handleDetectPage: (force?: boolean) => Promise<void>
  handleSaveMolecule: (newSmiles: string, newName?: string) => Promise<void>
}

export function usePdfDetections(args: UsePdfDetectionsArgs): UsePdfDetectionsResult {
  const {
    doc, libraryRoot, viewerKey,
    currentPage, currentPageDataUrl, pageInfo, pageTextItems, enrichResults,
    pageDetections, setPageDetections,
  } = args

  const [isDetecting, setIsDetecting] = useState(false)
  // ``selectedDetection`` lives on the façade. We expose a setter here so the
  // public contract stays unchanged; behaviourally the state is read by the
  // façade snapshot effect and mutated by the keyboard/wheel/jump wrappers.
  const [selectedDetection, setSelectedDetection] = useState<number | null>(
    viewerSnapshots.get(viewerKey)?.selectedDetection ?? null,
  )

  // 本会话内真正点过"识别"的页。流水线检测缓存已有行的页面不能算"已检测"，
  // 否则实时识别按钮会被误短路（覆盖层读源与写入 molecule_detections 解耦）。
  const interactivelyDetectedPages = useRef(new Set<number>())

  // 切页时只清空选中态。pageDetections 以页码为键、覆盖层只读当前页
  // （pageDetections.get(currentPage)），旧页条目就是该页的 bbox 缓存，
  // 不能删——文档级加载每文档只请求一次，删掉后切回该页无缓存可画，
  // 识别框会永久消失。
  // ``selectedDetection`` is also cleared here so any currentPage change —
  // even one not triggered by the façade's keyboard/wheel/jump wrappers —
  // drops the overlay safely.
  useEffect(() => {
    setSelectedDetection(null)
  }, [currentPage, setSelectedDetection])

  // 文本层条目在页面渲染后才到达，通常晚于文档级 overlay 请求；当前页文本就绪
  // 后为该页缺 context_text 的检测结果补 ROI 文本（hover tooltip 用）。
  const currentTextItemCount = pageTextItems.get(currentPage)?.length ?? 0
  useEffect(() => {
    setPageDetections(prev => {
      const rows = prev.get(currentPage)
      if (!rows || rows.length === 0 || !rows.some(r => !r.context_text)) return prev
      const enriched = enrichResults(rows, currentPage)
      if (enriched === rows) return prev
      const next = new Map(prev)
      next.set(currentPage, enriched)
      return next
    })
  }, [currentPage, currentTextItemCount, enrichResults, setPageDetections])

  const handleDetectPage = useCallback(async (force = false) => {
    if (!currentPageDataUrl || !pageInfo) {
      showToast('页面尚未渲染完成，请稍候', 'info')
      return
    }
    // 验证 pageInfo 和 currentPageDataUrl 属于当前页
    if (pageInfo.pageNumber !== currentPage) {
      if (import.meta.env.DEV) console.warn(`[PdfViewer] 检测页面不匹配: pageInfo.pageNumber=${pageInfo.pageNumber}, currentPage=${currentPage}`)
      showToast('页面状态异常，请稍候重试', 'warning')
      return
    }
    if (!force && interactivelyDetectedPages.current.has(currentPage)) {
      showToast(`第 ${currentPage} 页已检测`, 'info')
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
      // 验证返回的结果确实属于当前页
      const validatedResults = results.filter(r => {
        // eslint-disable-next-line @typescript-eslint/no-unnecessary-condition
        if (r.page_idx !== null && r.page_idx !== undefined) {
          return r.page_idx === currentPage - 1
        }
        return true
      })
      if (validatedResults.length < results.length) {
        if (import.meta.env.DEV) console.warn(`[PdfViewer] 过滤掉 ${results.length - validatedResults.length} 个不属于当前页的检测结果`)
      }
      const enriched = enrichResults(validatedResults, currentPage)
      try {
        // 存 0-based 页码，与 pipeline persist 写入的行同语义。
        await savePageDetections(libraryRoot, doc.doc_id, currentPage - 1, enriched)
      } catch (saveError) {
        console.warn('[PdfViewer] Failed to save detections:', saveError)
      }
      setPageDetections(prev => { const next = new Map(prev); next.set(currentPage, enriched); return next })
      interactivelyDetectedPages.current.add(currentPage)
      showToast(
        validatedResults.length > 0 ? `检测到 ${validatedResults.length} 个分子` : '未检测到分子',
        validatedResults.length > 0 ? 'success' : 'info',
      )
    } catch (e) {
      console.error('Detection failed:', e)
      showToast('检测失败: ' + getUserFacingError(e), 'error')
    } finally { setIsDetecting(false) }
  }, [currentPageDataUrl, pageInfo, currentPage, libraryRoot, doc.doc_id, enrichResults, setPageDetections, setSelectedDetection])

  const handleSaveMolecule = useCallback(async (newSmiles: string, newName?: string) => {
    if (selectedDetection === null) return
    const detections = pageDetections.get(currentPage) || []
    if (selectedDetection >= detections.length) return
    const current = detections[selectedDetection]
    const updated = [...detections]
    const name = newName?.trim() || current.name
    updated[selectedDetection] = {
      ...current,
      name,
      smiles: newSmiles,
      esmiles: newSmiles,
      moldet_conf: 1,
    }
    try {
      if (current.evidence_id) {
        await updateMoleculeEvidence(doc.doc_id, current.evidence_id, name, newSmiles)
      }
      await savePageDetections(libraryRoot, doc.doc_id, currentPage - 1, updated)
    } catch (e) {
      showToast('分子保存失败: ' + getUserFacingError(e), 'error')
      throw e
    }
    setPageDetections(prev => {
      const next = new Map(prev)
      next.set(currentPage, updated)
      return next
    })
    showToast('分子结构和标签已更新', 'success')
  }, [currentPage, doc.doc_id, libraryRoot, pageDetections, selectedDetection, setPageDetections])

  // ``pageTextItems`` is exposed via the navigation hook so future
  // enrichResults enhancements can read it; suppress the unused warning by
  // reading it through the args proxy.
  void pageTextItems

  return {
    pageDetections, setPageDetections,
    isDetecting, setIsDetecting,
    selectedDetection, setSelectedDetection,
    handleDetectPage,
    handleSaveMolecule,
  }
}
