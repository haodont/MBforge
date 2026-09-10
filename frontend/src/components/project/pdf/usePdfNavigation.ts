/**
 * PDF viewer navigation — page index, zoom, scroll container, keyboard/wheel
 * handling, scroll-to-detection, and per-page render state owned by the canvas
 * (pageInfo, currentPageDataUrl, text items).
 *
 * Pure UI/navigation layer: no detection cache, no OCR layout. The page-render
 * state lives here because every consumer (overlay rendering, scroll-to-target,
 * detection enrichment) reads the same page-metadata pair.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { API_BASE } from '@/api/http/_utils'
import { extractRoiText } from '@/utils/roiText'
import type { DocumentEntry, ExtractionResult } from '@/types'
import type { TextItem } from '@/utils/roiText'

export interface PageRenderInfo {
  pageNumber: number
  width: number
  height: number
  originalWidth: number
  originalHeight: number
  scale: number
}

export interface UsePdfNavigationArgs {
  doc: DocumentEntry
  libraryRoot: string
  initialPage?: number
  /** Initial page render snapshot from the LRU cache (if any). */
  initialSnapshot?: {
    currentPage?: number
    pdfScale?: number
    showTextLayer?: boolean
    showTextPanel?: boolean
  }
}

export interface UsePdfNavigationResult {
  /** Absolute filesystem path of the current document, for sibling hooks. */
  absDocPath: string
  currentPage: number
  setCurrentPage: React.Dispatch<React.SetStateAction<number>>
  pdfScale: number
  setPdfScale: React.Dispatch<React.SetStateAction<number>>
  pdfPageCount: number
  setPdfPageCount: React.Dispatch<React.SetStateAction<number>>
  showTextLayer: boolean
  setShowTextLayer: React.Dispatch<React.SetStateAction<boolean>>
  showTextPanel: boolean
  setShowTextPanel: React.Dispatch<React.SetStateAction<boolean>>
  pageJumpInput: string
  setPageJumpInput: React.Dispatch<React.SetStateAction<string>>
  pdfUrl: string
  pdfLoading: boolean
  pdfScrollRef: React.RefObject<HTMLDivElement | null>
  pageInfo: PageRenderInfo | null
  pageInfoRef: React.RefObject<PageRenderInfo | null>
  currentPageDataUrl: string | null
  pageTextItems: Map<number, TextItem[]>
  setPageTextItems: React.Dispatch<React.SetStateAction<Map<number, TextItem[]>>>
  // Derived values
  currentTextItems: TextItem[]
  currentTextTotal: number
  hasTextLayer: boolean
  canDetect: boolean
  // Handlers
  handleZoomIn: () => void
  handleZoomOut: () => void
  handleZoomReset: () => void
  handleJumpToPage: () => number
  handleKeyDown: (e: React.KeyboardEvent<HTMLDivElement>) => void
  handleWheel: (e: React.WheelEvent<HTMLDivElement>) => void
  handlePageRendered: (info: PageRenderInfo) => void
  handleImageReady: (pageNum: number, dataUrl: string) => void
  handlePageCount: (count: number) => void
  handleTextContent: (
    page: number,
    items: { str: string; x: number; y: number; width: number; height: number }[],
  ) => void
  scrollToDetection: (detection: ExtractionResult) => void
  // Enriched-results helper used by detection + recognition flows.
  enrichResults: (results: ExtractionResult[], pageNum: number) => ExtractionResult[]
}

const WHEEL_SWITCH_COOLDOWN_MS = 200

function normalizePath(p: string): string {
  return p.replace(/^\\\\\?\\/, '').replace(/^\?\//, '').replace(/\\/g, '/')
}

export function usePdfNavigation(args: UsePdfNavigationArgs): UsePdfNavigationResult {
  const { doc, libraryRoot, initialPage, initialSnapshot } = args

  const [currentPage, setCurrentPage] = useState(initialPage ?? initialSnapshot?.currentPage ?? 1)
  const [pdfScale, setPdfScale] = useState(Math.max(1, initialSnapshot?.pdfScale ?? 1))
  const [pdfPageCount, setPdfPageCount] = useState(0)
  const [showTextLayer, setShowTextLayer] = useState(true)
  const [showTextPanel, setShowTextPanel] = useState(false)
  const [pageJumpInput, setPageJumpInput] = useState('')

  const [pageInfo, setPageInfo] = useState<PageRenderInfo | null>(null)
  const pageInfoRef = useRef<PageRenderInfo | null>(null)
  const [currentPageDataUrl, setCurrentPageDataUrl] = useState<string | null>(null)
  const [pageTextItems, setPageTextItems] = useState<Map<number, TextItem[]>>(new Map())

  const [pdfUrl, setPdfUrl] = useState('')
  const [pdfLoading, setPdfLoading] = useState(true)

  const pdfScrollRef = useRef<HTMLDivElement>(null)
  const wheelSwitchAtRef = useRef(0)

  // Resolve the absolute PDF path for the current document. This is computed
  // here so sibling hooks (usePdfOcr) can receive it without re-deriving it.
  const absDocPath = useMemo(() => {
    const root = libraryRoot
    if (!root) return doc.path
    const pdfPath = doc.source_path || doc.path
    return pdfPath.includes(':') || pdfPath.startsWith('/')
      ? normalizePath(pdfPath)
      : `${normalizePath(root).replace(/\/$/, '')}/${pdfPath.replace(/\\/g, '/')}`
  }, [doc.path, doc.source_path, libraryRoot])

  // Build the PDF file URL whenever the document or library root changes.
  useEffect(() => {
    let cancelled = false
    setPdfUrl('')
    setPdfLoading(true)
    const url = `${API_BASE}/library/documents/${encodeURIComponent(doc.doc_id)}/file?library_root=${encodeURIComponent(libraryRoot)}`
    // eslint-disable-next-line @typescript-eslint/no-unnecessary-condition
    if (!cancelled) { setPdfUrl(url); setPdfLoading(false) }
    return () => { cancelled = true }
  }, [doc.doc_id, libraryRoot])

  // 切页时清空当前页渲染状态，避免旧页面的 dataUrl / pageInfo 被复用到新页，
  // 导致 MoldDet 把上一页的识别结果存到当前页（如第 2 页结果显示在第 3 页）。
  useEffect(() => {
    setCurrentPageDataUrl(null)
    setPageInfo(null)
    pageInfoRef.current = null
    // Note: selectedDetection is owned by usePdfDetections — the facade passes
    // a clearing setter through that hook's contract if needed.
  }, [currentPage])

  // Focus the scroll container on mount / doc change so keyboard nav works.
  useEffect(() => { pdfScrollRef.current?.focus() }, [doc.doc_id])

  const enrichResults = useCallback((results: ExtractionResult[], pageNum: number) => {
    const textItems = pageTextItems.get(pageNum) || []
    const info = pageInfoRef.current
    if (!info) return results
    return results.map(r => {
      if (r.bbox_pdf && textItems.length > 0 && !r.context_text) {
        return { ...r, context_text: extractRoiText(r.bbox_pdf, textItems, info.originalHeight) }
      }
      return r
    })
  }, [pageTextItems])

  const handlePageRendered = useCallback((info: PageRenderInfo) => {
    // 只接受当前页的渲染结果，防止旧页面的数据污染
    if (info.pageNumber !== currentPage) {
      console.debug(`[PdfViewer] 忽略非当前页的渲染结果: page=${info.pageNumber}, current=${currentPage}`)
      return
    }
    // 验证页面尺寸合理性（防止异常数据）
    if (info.width <= 0 || info.height <= 0 || info.originalWidth <= 0 || info.originalHeight <= 0) {
      if (import.meta.env.DEV) console.warn('[PdfViewer] 忽略异常的页面尺寸:', info)
      return
    }
    setPageInfo(info)
    pageInfoRef.current = info
  }, [currentPage])

  const handleImageReady = useCallback((pageNum: number, dataUrl: string) => {
    // 只接受当前页的图像数据
    if (pageNum !== currentPage) {
      console.debug(`[PdfViewer] 忽略非当前页的图像数据: page=${pageNum}, current=${currentPage}`)
      return
    }
    // 验证 dataUrl 有效性
    if (!dataUrl || !dataUrl.startsWith('data:image/')) {
      if (import.meta.env.DEV) console.warn('[PdfViewer] 忽略无效的图像数据')
      return
    }
    setCurrentPageDataUrl(dataUrl)
  }, [currentPage])

  const handlePageCount = useCallback((count: number) => setPdfPageCount(count), [])

  const handleTextContent = useCallback((page: number, items: TextItem[]) => {
    setPageTextItems(prev => { const next = new Map(prev); next.set(page, items); return next })
  }, [])

  const handleZoomIn = useCallback(() => setPdfScale(s => Math.min(s + 0.3, 5)), [])
  const handleZoomOut = useCallback(() => setPdfScale(s => Math.max(s - 0.3, 1)), [])
  const handleZoomReset = useCallback(() => setPdfScale(1), [])

  const handleJumpToPage = useCallback((): number => {
    const n = parseInt(pageJumpInput, 10)
    if (n > 0) {
      setCurrentPage(n)
      setPageJumpInput('')
      return n
    }
    return currentPage
  }, [pageJumpInput, currentPage])

  const handleKeyDown = useCallback((e: React.KeyboardEvent<HTMLDivElement>) => {
    if (e.key === 'ArrowLeft' || e.key === 'ArrowUp' || e.key === 'PageUp') {
      e.preventDefault()
      setCurrentPage(p => Math.max(1, p - 1))
    } else if (e.key === 'ArrowRight' || e.key === 'ArrowDown' || e.key === 'PageDown' || e.key === ' ') {
      e.preventDefault()
      setCurrentPage(p => Math.min(pdfPageCount || 1, p + 1))
    }
  }, [pdfPageCount])

  const handleWheel = useCallback((e: React.WheelEvent<HTMLDivElement>) => {
    const el = pdfScrollRef.current
    if (!el || pdfLoading || !pdfUrl) return
    const { scrollTop, scrollHeight, clientHeight } = el
    const atTop = scrollTop <= 0
    const atBottom = scrollTop + clientHeight >= scrollHeight - 1
    if ((e.deltaY < 0 && atTop) || (e.deltaY > 0 && atBottom)) {
      // 不再调用 preventDefault()，避免 passive event listener 警告；
      // 用时间门控降低连续滚轮触发翻页的速度。
      const now = Date.now()
      if (now - wheelSwitchAtRef.current < WHEEL_SWITCH_COOLDOWN_MS) return
      wheelSwitchAtRef.current = now
      if (e.deltaY < 0) {
        setCurrentPage(p => Math.max(1, p - 1))
      } else {
        setCurrentPage(p => Math.min(pdfPageCount || 1, p + 1))
      }
    }
  }, [pdfLoading, pdfUrl, pdfPageCount])

  const scrollToDetection = useCallback((detection: ExtractionResult) => {
    if (!detection.bbox_pdf || !pageInfoRef.current) return
    const container = pdfScrollRef.current
    if (!container) return

    const [, y1, , y2] = detection.bbox_pdf
    const info = pageInfoRef.current

    // 检查是否是连续模式（容器内有 [data-page] 元素）
    const isContinuousMode = container.querySelector('[data-page]')

    if (isContinuousMode) {
      // 连续模式：找到当前页的元素，计算偏移量
      const pageEl = container.querySelector(`[data-page="${detection.page_idx !== null ? detection.page_idx + 1 : currentPage}"]`)
      if (pageEl) {
        const pageRect = pageEl.getBoundingClientRect()
        const containerRect = container.getBoundingClientRect()
        // 计算检测框在页面内的相对位置
        const cssY = (info.originalHeight - y2) * info.scale
        const cssY2 = (info.originalHeight - y1) * info.scale
        const centerY = (cssY + cssY2) / 2
        // 滚动到检测框居中
        container.scrollTo({
          top: pageEl.scrollTop + (pageRect.top - containerRect.top) + centerY - container.clientHeight / 2,
          behavior: 'smooth',
        })
      }
    } else {
      // 单页模式：直接计算 CSS 坐标
      const cssY = (info.originalHeight - y2) * info.scale
      const cssY2 = (info.originalHeight - y1) * info.scale
      const centerY = (cssY + cssY2) / 2
      container.scrollTo({
        top: Math.max(0, centerY - container.clientHeight / 2),
        behavior: 'smooth',
      })
    }
  }, [currentPage])

  const currentTextItems = pageTextItems.get(currentPage) || []
  const currentTextTotal = currentTextItems.reduce((s, i) => s + i.str.length, 0)
  const hasTextLayer = currentTextTotal > 10
  const canDetect = !!currentPageDataUrl && !!pageInfo

  return {
    currentPage, setCurrentPage,
    absDocPath,
    pdfScale, setPdfScale,
    pdfPageCount, setPdfPageCount,
    showTextLayer, setShowTextLayer,
    showTextPanel, setShowTextPanel,
    pageJumpInput, setPageJumpInput,
    pdfUrl, pdfLoading,
    pdfScrollRef,
    pageInfo, pageInfoRef,
    currentPageDataUrl,
    pageTextItems, setPageTextItems,
    currentTextItems, currentTextTotal, hasTextLayer, canDetect,
    handleZoomIn, handleZoomOut, handleZoomReset,
    handleJumpToPage,
    handleKeyDown, handleWheel,
    handlePageRendered, handleImageReady, handlePageCount, handleTextContent,
    scrollToDetection,
    enrichResults,
  }
}
