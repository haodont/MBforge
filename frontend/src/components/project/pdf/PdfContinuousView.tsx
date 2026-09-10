import { useEffect, useMemo, useRef, useState, type ReactNode, type RefObject } from 'react'
import PdfCanvas from '@/components/PdfCanvas'

interface Props {
  url: string
  pageCount: number
  currentPage: number
  scale: number
  showTextLayer: boolean
  scrollRootRef: RefObject<HTMLDivElement | null>
  overlay?: ReactNode
  onPageChange: (page: number) => void
  onPageRendered: (info: {
    pageNumber: number
    width: number
    height: number
    originalWidth: number
    originalHeight: number
    scale: number
  }) => void
  onImageReady: (page: number, dataUrl: string) => void
  onTextContent: (page: number, items: { str: string; x: number; y: number; width: number; height: number }[]) => void
  onPageCount: (count: number) => void
}

/**
 * Continuous PDF view with a small render window around the visible page.
 * Placeholders keep the scroll height stable while off-screen canvases stay
 * unmounted, preventing a whole-document render storm.
 */
export default function PdfContinuousView({
  url,
  pageCount,
  currentPage,
  scale,
  showTextLayer,
  scrollRootRef,
  overlay,
  onPageChange,
  onPageRendered,
  onImageReady,
  onTextContent,
  onPageCount,
}: Props) {
  const pageRefs = useRef(new Map<number, HTMLDivElement>())
  const [visiblePage, setVisiblePage] = useState(currentPage)
  const renderPages = useMemo(() => {
    const count = pageCount || 1
    const start = Math.max(1, visiblePage - 1)
    const end = Math.min(count, visiblePage + 1)
    return Array.from({ length: end - start + 1 }, (_, index) => start + index)
  }, [pageCount, visiblePage])

  useEffect(() => {
    const root = scrollRootRef.current
    if (!root) return
    const observer = new IntersectionObserver(
      entries => {
        const intersecting = entries
          .filter(entry => entry.isIntersecting)
          .sort((a, b) => b.intersectionRatio - a.intersectionRatio)
        if (intersecting.length === 0) return
        const mostVisible = intersecting[0]
        const page = Number((mostVisible.target as HTMLElement).dataset.page)
        if (!Number.isFinite(page)) return
        setVisiblePage(page)
        onPageChange(page)
      },
      { root, rootMargin: '120px 0px', threshold: [0.25, 0.6, 0.9] },
    )
    pageRefs.current.forEach(element => observer.observe(element))
    return () => observer.disconnect()
  }, [onPageChange, renderPages, scrollRootRef])

  return (
    <div className="pdf-continuous-pages">
      {Array.from({ length: pageCount || 1 }, (_, index) => {
        const page = index + 1
        const isRendered = renderPages.includes(page)
        return (
          <div
            key={page}
            ref={element => {
              if (element) pageRefs.current.set(page, element)
              else pageRefs.current.delete(page)
            }}
            data-page={page}
            className="pdf-continuous-page"
          >
            {isRendered ? (
              <div className="pdf-continuous-page__canvas">
                <PdfCanvas
                  url={url}
                  pageNumber={page}
                  scale={scale}
                  generateImage={page === currentPage}
                  showTextLayer={showTextLayer}
                  onPageRendered={onPageRendered}
                  onImageReady={onImageReady}
                  onTextContent={onTextContent}
                  onPageCount={onPageCount}
                />
                {page === currentPage ? overlay : null}
              </div>
            ) : (
              <div className="pdf-continuous-page__placeholder" aria-hidden="true" />
            )}
            <span className="pdf-continuous-page__number">{page}</span>
          </div>
        )
      })}
    </div>
  )
}
