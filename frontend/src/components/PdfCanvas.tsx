import { memo, useEffect, useRef, useState, useCallback } from 'react'
import { useTranslation } from 'react-i18next'
import type { PDFDocumentProxy } from 'pdfjs-dist'
import * as pdfjsLib from 'pdfjs-dist'
import { createPdfDocumentCache } from './pdfDocumentCache'

function isTextItem(v: unknown): v is { str: string; transform: number[]; width: number; height: number } {
  return typeof v === 'object' && v !== null && 'str' in v && typeof v.str === 'string'
}

pdfjsLib.GlobalWorkerOptions.workerSrc = new URL(
  'pdfjs-dist/build/pdf.worker.mjs',
  import.meta.url,
).toString()

const DOC_CACHE_MAX = 3
const docCache = createPdfDocumentCache<PDFDocumentProxy>(
  DOC_CACHE_MAX,
  url => pdfjsLib.getDocument(url),
)

interface PageInfo {
  pageNumber: number
  width: number
  height: number
  originalWidth: number
  originalHeight: number
  scale: number
}

interface Props {
  url: string
  pageNumber: number
  scale?: number
  /** Single-page viewer viewport used as the 100% display baseline. */
  fitContainerRef?: React.RefObject<HTMLElement | null>
  generateImage?: boolean
  showTextLayer?: boolean
  onPageRendered?: (info: PageInfo) => void
  onImageReady?: (pageNumber: number, dataUrl: string) => void
  onTextContent?: (pageNumber: number, items: { str: string; x: number; y: number; width: number; height: number }[]) => void
  onTextLayerClick?: (pageNumber: number) => void
  onPageCount?: (count: number) => void
  className?: string
  style?: React.CSSProperties
}

const PdfCanvas = memo(function PdfCanvas({
  url,
  pageNumber,
  scale = 1,
  fitContainerRef,
  generateImage = false,
  showTextLayer = true,
  onPageRendered,
  onImageReady,
  onTextContent,
  onTextLayerClick,
  onPageCount,
  className,
  style,
}: Props) {
  const { t } = useTranslation()
  const containerRef = useRef<HTMLDivElement>(null)
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const textLayerRef = useRef<HTMLDivElement>(null)
  const lastOriginalRef = useRef<{ width: number; height: number } | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const totalPagesRef = useRef(0)
  const [totalPages, setTotalPages] = useState(0)
  const pdfDocRef = useRef<PDFDocumentProxy | null>(null)
  const renderTaskRef = useRef<pdfjsLib.RenderTask | null>(null)

  const onPageRenderedRef = useRef(onPageRendered)
  const onImageReadyRef = useRef(onImageReady)
  const onTextContentRef = useRef(onTextContent)
  const onPageCountRef = useRef(onPageCount)
  const generateImageRef = useRef(generateImage)

  useEffect(() => {
    onPageRenderedRef.current = onPageRendered
    onImageReadyRef.current = onImageReady
    onTextContentRef.current = onTextContent
    onPageCountRef.current = onPageCount
    generateImageRef.current = generateImage
  })

  const measureRenderedSize = useCallback(() => {
    const canvas = canvasRef.current
    const original = lastOriginalRef.current
    if (!canvas || !original) return
    const rect = canvas.getBoundingClientRect()
    if (!rect.width || !rect.height) return
    const layer = textLayerRef.current
    if (layer) {
      layer.style.width = `${rect.width}px`
      layer.style.height = `${rect.height}px`
    }
    onPageRenderedRef.current?.({
      pageNumber,
      width: rect.width,
      height: rect.height,
      originalWidth: original.width,
      originalHeight: original.height,
      scale: rect.height / original.height,
    })
  }, [pageNumber])

  const fitToWindow = useCallback(() => {
    const canvas = canvasRef.current
    const target = fitContainerRef?.current
    const original = lastOriginalRef.current
    if (!canvas || !target || !original) return
    const height = target.getBoundingClientRect().height
    if (!height || !original.height) return
    const displayHeight = height * scale
    const displayWidth = displayHeight * (original.width / original.height)
    canvas.style.width = `${displayWidth}px`
    canvas.style.height = `${displayHeight}px`
    measureRenderedSize()
  }, [fitContainerRef, measureRenderedSize, scale])

  // 只观察左侧窗口。fitToWindow 会修改 canvas 尺寸，不能再观察 canvas，
  // 否则 ResizeObserver 会被自己的回调反复触发。
  useEffect(() => {
    const target = fitContainerRef?.current
    if (!target || typeof ResizeObserver === 'undefined') return
    const observer = new ResizeObserver(fitToWindow)
    observer.observe(target)
    return () => observer.disconnect()
  }, [fitContainerRef, fitToWindow])

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)

    docCache.get(url)
      .then(doc => {
    if (cancelled) {
          // The document may be shared by several continuous-view pages.
          // Cache eviction, rather than an individual page unmount, owns cleanup.
          return
        }
        pdfDocRef.current = doc
        totalPagesRef.current = doc.numPages
        setTotalPages(doc.numPages)
        onPageCountRef.current?.(doc.numPages)
      })
      .catch((_: unknown) => {
        if (!cancelled) setError('Failed to load PDF')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })

    return () => {
      cancelled = true
      // Cancel any in-flight render before destroying the document.
      if (renderTaskRef.current) {
        try { renderTaskRef.current.cancel() } catch { /* ignore */ }
        renderTaskRef.current = null
      }
      pdfDocRef.current = null
    }
  }, [url])

  const renderTextLayerImpl = useCallback(async (page: pdfjsLib.PDFPageProxy, renderScale = scale) => {
    const container = textLayerRef.current
    if (!container) return

    const logicalViewport = page.getViewport({ scale: renderScale })
    const textContent = await page.getTextContent()

    container.innerHTML = ''
    container.style.width = `${logicalViewport.width}px`
    container.style.height = `${logicalViewport.height}px`

    if (onTextContentRef.current) {
      const items = (textContent.items as unknown[])
        .filter(isTextItem)
        .map(item => ({
          str: item.str,
          x: item.transform[4],
          y: item.transform[5],
          width: item.width,
          height: item.height,
        }))
      onTextContentRef.current(pageNumber, items)
    }
  }, [pageNumber, scale])

  const renderPage = useCallback(async () => {
    const doc = pdfDocRef.current
    const canvas = canvasRef.current
    const textLayerEl = textLayerRef.current
    if (!doc || !canvas) return

    // 取消上一次未完成的渲染 — pdf.js 不允许同一 canvas 并发 render()
    if (renderTaskRef.current) {
      try { renderTaskRef.current.cancel() } catch { /* ignore */ }
      renderTaskRef.current = null
    }

    try {
      const page = await doc.getPage(pageNumber)
      const dpr = window.devicePixelRatio || 1
      const originalViewport = page.getViewport({ scale: 1 })
      const fitHeight = fitContainerRef?.current?.getBoundingClientRect().height
      const renderScale = fitHeight && originalViewport.height
        ? (fitHeight / originalViewport.height) * scale
        : scale
      const viewport = page.getViewport({ scale: renderScale * dpr })
      const ctx = canvas.getContext('2d')
      if (!ctx) return

      canvas.width = viewport.width
      canvas.height = viewport.height
      canvas.style.width = `${viewport.width / dpr}px`
      canvas.style.height = `${viewport.height / dpr}px`
      ctx.clearRect(0, 0, viewport.width, viewport.height)
      ctx.scale(dpr, dpr)
      const task = page.render({
        canvasContext: ctx,
        viewport: page.getViewport({ scale: renderScale }),
      })
      renderTaskRef.current = task
      try {
        await task.promise
      } catch (e) {
        // 取消会抛 RenderCancelledException — 静默吞掉
        if ((e as Error).message.includes('cancelled')) return
        throw e
      } finally {
        if (renderTaskRef.current === task) renderTaskRef.current = null
      }

      lastOriginalRef.current = {
        width: originalViewport.width,
        height: originalViewport.height,
      }
      // 100% fills the left pane; larger zooms scale that fitted rectangle
      // uniformly. Re-read after layout so overlays use actual CSS pixels.
      window.requestAnimationFrame(() => {
        fitToWindow()
        measureRenderedSize()
      })

      if (generateImage) {
        // PNG encoding is expensive. Keep it off the render's synchronous path
        // so clicks, scrolling, and React updates are not blocked by a full-page
        // bitmap conversion.
        canvas.toBlob(blob => {
          if (!blob) return
          const reader = new FileReader()
          reader.onload = () => {
            if (typeof reader.result === 'string') {
              onImageReadyRef.current?.(pageNumber, reader.result)
            }
          }
          reader.readAsDataURL(blob)
        }, 'image/png')
      }

      if (textLayerEl) {
        void renderTextLayerImpl(page, renderScale)
      }
    } catch (e) {
      console.error('PDF render error:', e)
    }
  }, [fitContainerRef, fitToWindow, generateImage, measureRenderedSize, pageNumber, scale, renderTextLayerImpl])

  useEffect(() => {
    if (!loading && !error) void renderPage()
  }, [loading, error, renderPage])

  return (
    <div
      ref={containerRef}
      className={className}
      style={{ position: 'relative', ...style }}
    >
      {loading && (
        <div style={{
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          height: '100%', color: 'var(--text-muted)', fontSize: '13px',
        }}>
          加载 PDF...
        </div>
      )}
      {error && (
        <div style={{
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          height: '100%', color: 'var(--danger)', fontSize: '13px',
        }}>
          {error}
        </div>
      )}
      <canvas
        ref={canvasRef}
        style={{
          display: loading || error ? 'none' : 'block',
          maxWidth: 'none',
          margin: 0,
        }}
      />
      <div
        ref={textLayerRef}
        onClick={() => onTextLayerClick?.(pageNumber)}
        style={{
          position: 'absolute',
          top: 0,
          left: '50%',
          transform: 'translateX(-50%)',
          cursor: showTextLayer ? 'text' : 'default',
          pointerEvents: showTextLayer ? 'auto' : 'none',
          display: loading || error || !showTextLayer ? 'none' : 'block',
          zIndex: 1,
          background: 'transparent',
        }}
        title={t('pdfResult.label')}
      />
      {totalPages > 0 && (
        <div style={{
          position: 'absolute', bottom: '8px', left: '50%',
          transform: 'translateX(-50%)',
          fontSize: '11px', color: 'var(--text-muted)',
          background: 'var(--bg-surface)', padding: '2px 8px',
          borderRadius: '4px', border: '1px solid var(--border)',
          zIndex: 2,
        }}>
          {pageNumber} / {totalPages}
        </div>
      )}
    </div>
  )
})

export default PdfCanvas
