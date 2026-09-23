import { forwardRef, useCallback, useEffect, useImperativeHandle, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import type { OcrBlock } from '@/api/http/pdf'
import PdfCanvas from '@/components/PdfCanvas'
import MoleculeOverlay from '@/components/MoleculeOverlay'
import OcrOverlay from '@/components/OcrOverlay'
import ScrollColumn from '../ui/ScrollColumn'
import Button from '../ui/Button'
import IconButton from '../ui/IconButton'
import { LoadingState } from '../ui/LoadingState'
import type { DocumentEntry, ExtractionResult } from '@/types'
import { usePdfViewer } from './pdf/usePdfViewer'
import PdfFloatingControls from './pdf/PdfFloatingControls'
import PdfContinuousView from './pdf/PdfContinuousView'
import PageEvidencePane from './PageEvidencePane'
import { ChevronLeftIcon, ChevronRightIcon } from '@/components/icons'
import { RdkitStructure } from '@/components/chat/markdownExtensions'
import { pdfToCss } from '@/utils/pdf'
import MoleculeEditorDialog from '@/components/molecule/MoleculeEditorDialog'
import { cropImageUrl, type PatentFactsArtifact, type PatentFactsMeasurement } from '@/api/http/library'
import { useDocumentPatentFacts } from '@/api/query/hooks'
import Badge from '@/components/ui/Badge'

/** Imperative handle exposed to a parent (DocumentViewer). */
export interface PdfViewerHandle {
  setCurrentPage: (page: number) => void
  scrollToDetection: (detection: ExtractionResult) => void
}

interface Props {
  doc: DocumentEntry
  libraryRoot: string
  onClose: () => void
  onMoleculeClick?: (info: {
    page: number
    bbox?: [number, number, number, number] | null
  }) => void
  initialPage?: number
  initialBbox?: [number, number, number, number]
  viewerKey?: string
}

const DIRECTORY_KINDS = new Set(['title', 'head', 'sec', 'toc'])

const PdfViewer = forwardRef<PdfViewerHandle, Props>(function PdfViewer(
  { doc, libraryRoot, onClose: _onClose, onMoleculeClick, initialPage, initialBbox, viewerKey },
  ref,
) {
  const { t } = useTranslation()
  // Destructure at the hook call site: the hook's return object also carries
  // refs (pdfScrollRef / pageInfoRef), and reading properties off that object
  // during render trips react-hooks/refs. Destructured values are plain state.
  const {
    currentPage, setCurrentPage,
    isDetecting, selectedDetection, setSelectedDetection,
    pageInfo, pdfScale,
    showTextLayer,
    pageJumpInput, setPageJumpInput,
    setShowTextPanel, pdfPageCount,
    ocrBlocks, selectedOcrIndex, setSelectedOcrIndex,
    pdfUrl, pdfLoading, pdfScrollRef,
    currentDetections, hasTextLayer, canDetect,
    handleDetectPage, handleRecognizePage,
    handlePageRendered, handleImageReady, handlePageCount, handleTextContent,
    handleSaveMolecule,
    handleZoomIn, handleZoomOut, handleZoomReset,
    handleJumpToPage, handleKeyDown, handleWheel, scrollToDetection,
  } = usePdfViewer(doc, libraryRoot, viewerKey, initialPage)
  const [isResultPaneCollapsed, setIsResultPaneCollapsed] = useState(false)
  const [sourcePaneWidth, setSourcePaneWidth] = useState<number | null>(null)
  const [selectedEvidenceId, setSelectedEvidenceId] = useState<string | null>(null)
  const [sidePaneTab, setSidePaneTab] = useState<'evidence' | 'molecules' | 'directory'>('evidence')
  const [editingDetectionIndex, setEditingDetectionIndex] = useState<number | null>(null)
  const [continuousMode, setContinuousMode] = useState(false)
  const pendingDirectoryJumpRef = useRef<{ page: number; index: number; evidenceId: string } | null>(null)
  const { data: patentFactsResult } = useDocumentPatentFacts(doc.doc_id, libraryRoot)
  const patentFacts = patentFactsResult?.ok ? patentFactsResult.data : null
  const directoryEntries = useMemo(() => ocrBlocks
    .filter(block => block.page > 0 && DIRECTORY_KINDS.has(block.kind ?? '') && Boolean(block.content?.trim()))
    .sort((a, b) => a.page - b.page || b.bbox[3] - a.bbox[3]), [ocrBlocks])
  const pdfCanvasStyle = useMemo(() => ({
    background: '#fff',
    boxShadow: 'var(--shadow-md)',
  }), [])
  const openTextPanel = useCallback(() => setShowTextPanel(true), [setShowTextPanel])
  const handleContinuousPageChange = useCallback((page: number) => setCurrentPage(page), [setCurrentPage])

  useEffect(() => {
    if (!pageInfo || !pageInfo.width || sourcePaneWidth === pageInfo.width) return
    setSourcePaneWidth(pageInfo.width)
  }, [pageInfo, sourcePaneWidth])

  useEffect(() => {
    const pending = pendingDirectoryJumpRef.current
    if (pending?.page === currentPage) {
      setSelectedEvidenceId(pending.evidenceId)
      setSelectedOcrIndex(pending.index)
      pendingDirectoryJumpRef.current = null
    } else {
      setSelectedEvidenceId(null)
      setSelectedOcrIndex(null)
    }
    setEditingDetectionIndex(null)
  }, [currentPage, setSelectedEvidenceId, setSelectedOcrIndex])

  const handleDirectorySelect = useCallback((block: OcrBlock) => {
    setSelectedDetection(null)
    if (block.page === currentPage) {
      pendingDirectoryJumpRef.current = null
      setSelectedEvidenceId(block.evidence_id)
      setSelectedOcrIndex(block.index)
    } else {
      pendingDirectoryJumpRef.current = {
        page: block.page,
        index: block.index,
        evidenceId: block.evidence_id,
      }
      setSelectedEvidenceId(null)
      setSelectedOcrIndex(null)
    }
    if (continuousMode) {
      const pageElement = pdfScrollRef.current?.querySelector<HTMLElement>(`[data-page="${block.page}"]`)
      if (pageElement) pageElement.scrollIntoView({ block: 'start', behavior: 'smooth' })
      else setContinuousMode(false)
    }
    setCurrentPage(block.page)
  }, [continuousMode, currentPage, pdfScrollRef, setCurrentPage, setSelectedDetection, setSelectedEvidenceId, setSelectedOcrIndex])
  // 覆盖层读源：文档打开时一次性加载全文 bbox（流水线 v2 证据 ∪ 交互识别写入的
  // molecule_detections，后端逐页去重，含低置信/被拒候选，框颜色编码置信度）；
  // MoleculeOverlay 自身保留 bbox 有效性过滤。置信度阈值过滤已随旧按页读源移除
  // （阈值滑条本就无 UI 入口）。
  const visibleDetections = currentDetections
  const deepLinkKeyRef = useRef<string | null>(null)

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

  const pageOverlay = pageInfo && visibleDetections.length > 0 ? (
    <MoleculeOverlay
      detections={visibleDetections}
      renderWidth={pageInfo.width}
      renderHeight={pageInfo.height}
      originalHeight={pageInfo.originalHeight}
      originalWidth={pageInfo.originalWidth}
      scale={pageInfo.scale}
      currentPage={currentPage}
      selectedIndex={selectedDetection ?? undefined}
      onSelect={(index, detection) => {
        setSelectedDetection(index)
        setSelectedOcrIndex(null)
        setSelectedEvidenceId(detection?.evidence_id ?? null)
        onMoleculeClick?.({ page: currentPage, bbox: detection?.bbox_pdf })
      }}
      onRecognize={handleRecognizePage}
      isRecognizing={isDetecting}
    />
  ) : null

  const ocrPageOverlay = pageInfo && ocrBlocks.length > 0 ? (
    <OcrOverlay
      blocks={ocrBlocks}
      renderWidth={pageInfo.width}
      renderHeight={pageInfo.height}
      originalHeight={pageInfo.originalHeight}
      originalWidth={pageInfo.originalWidth}
      scale={pageInfo.scale}
      page={currentPage}
      selectedIndex={selectedOcrIndex ?? undefined}
      onSelect={(index, block) => {
        setSelectedOcrIndex(index)
        setSelectedDetection(null)
        setSelectedEvidenceId(block?.evidence_id ?? null)
        onMoleculeClick?.({ page: currentPage, bbox: block?.bbox })
      }}
    />
  ) : null

  useImperativeHandle(ref, () => ({
    setCurrentPage: (page: number) => setCurrentPage(page),
    scrollToDetection: (detection: ExtractionResult) => scrollToDetection(detection),
  }), [scrollToDetection, setCurrentPage])

  return (
    <div className="pdf-viewer">
      <div
        className={`pdf-dual-pane${sourcePaneWidth !== null ? ' pdf-dual-pane--source-locked' : ''}${isResultPaneCollapsed ? ' pdf-dual-pane--result-collapsed' : ''}`}
        style={sourcePaneWidth !== null ? { '--pdf-source-width': `${sourcePaneWidth}px` } : undefined}
      >
        {/* 左侧：PDF 内容 + 所有 bbox overlay */}
        <div className="pdf-source-pane">
          <ScrollColumn
            ref={pdfScrollRef}
            tabIndex={0}
            onKeyDown={handleKeyDown}
            onWheel={handleWheel}
            className="pdf-single-page"
            style={{ background: 'var(--bg-base)' }}
          >
            <div className="pdf-canvas-wrap">
              {pdfLoading || !pdfUrl ? (
                <LoadingState
                  variant="spinner"
                  message={t('pdf.loading')}
                  className="pdf-loading"
                />
              ) : continuousMode ? (
                <PdfContinuousView
                  url={pdfUrl}
                  pageCount={pdfPageCount}
                  currentPage={currentPage}
                  scale={pdfScale}
                  showTextLayer={showTextLayer && hasTextLayer}
                  scrollRootRef={pdfScrollRef}
                  overlay={<>{pageOverlay}{ocrPageOverlay}</>}
                  onPageChange={handleContinuousPageChange}
                  onPageRendered={handlePageRendered}
                  onImageReady={handleImageReady}
                  onTextContent={handleTextContent}
                  onPageCount={handlePageCount}
                />
              ) : (
                <PdfCanvas
                  url={pdfUrl}
                  pageNumber={currentPage}
                  scale={pdfScale}
                  fitContainerRef={pdfScrollRef}
                  generateImage
                  showTextLayer={showTextLayer && hasTextLayer}
                  onPageRendered={handlePageRendered}
                  onImageReady={handleImageReady}
                  onTextContent={handleTextContent}
                  onTextLayerClick={openTextPanel}
                  onPageCount={handlePageCount}
                  style={pdfCanvasStyle}
                />
              )}
              {!continuousMode && <>
                {pageOverlay}
                {ocrPageOverlay}
                {initialPage === currentPage && initialBbox && pageInfo && (
                  <LocationHighlight bbox={initialBbox} pageInfo={pageInfo} />
                )}
              </>}
            </div>
          </ScrollColumn>

          <PdfFloatingControls
            pdfScale={pdfScale}
            onZoomIn={handleZoomIn}
            onZoomOut={handleZoomOut}
            onZoomReset={handleZoomReset}
            currentPage={currentPage}
            pdfPageCount={pdfPageCount}
            pageJumpInput={pageJumpInput}
            onPageJumpInputChange={setPageJumpInput}
            onJumpToPage={handleJumpToPage}
            onPrevPage={() => { setCurrentPage(p => Math.max(1, p - 1)); setSelectedDetection(null); requestAnimationFrame(() => pdfScrollRef.current?.focus()) }}
            onNextPage={() => { setCurrentPage(p => p + 1); requestAnimationFrame(() => pdfScrollRef.current?.focus()) }}
            continuousMode={continuousMode}
            onToggleContinuous={() => setContinuousMode(mode => !mode)}
          />
        </div>

        {/* 右侧：当前页 SQL 证据与分子；事实证据显示在分子卡片内 */}
        <aside className={`pdf-document-sidebar${isResultPaneCollapsed ? ' is-collapsed' : ''}`} aria-label={t('pdf.moleculesHeader')}>
          {isResultPaneCollapsed ? (
            <IconButton
              size={32}
              className="pdf-document-sidebar__collapse-button"
              onClick={() => setIsResultPaneCollapsed(false)}
              ariaLabel={t('pdf.sidebarExpand')}
              title={t('pdf.sidebarExpandTitle')}
            >
              <ChevronLeftIcon size={16} />
            </IconButton>
          ) : (
            <>
              <div className="pdf-document-sidebar__tabs" role="tablist" aria-label={t('pdf.moleculesHeader')}>
                <button type="button" role="tab" aria-selected={sidePaneTab === 'evidence'} className={sidePaneTab === 'evidence' ? 'is-active' : ''} onClick={() => setSidePaneTab('evidence')}>{t('pdf.tabEvidence')}</button>
                <button type="button" role="tab" aria-selected={sidePaneTab === 'molecules'} className={sidePaneTab === 'molecules' ? 'is-active' : ''} onClick={() => setSidePaneTab('molecules')}>{t('pdf.tabMolecules')}</button>
                <button type="button" role="tab" aria-selected={sidePaneTab === 'directory'} className={sidePaneTab === 'directory' ? 'is-active' : ''} onClick={() => setSidePaneTab('directory')}>{t('pdf.tabDirectory')}</button>
                <IconButton
                  size={28}
                  className="pdf-document-sidebar__collapse-button"
                  onClick={() => setIsResultPaneCollapsed(true)}
                  ariaLabel={t('pdf.sidebarCollapse')}
                  title={t('pdf.sidebarCollapseTitle')}
                >
                  <ChevronRightIcon size={16} />
                </IconButton>
              </div>
              <div className="pdf-document-sidebar__content">
                {sidePaneTab === 'evidence' && (
                  <PageEvidencePane
                    docId={doc.doc_id}
                    page={currentPage}
                    libraryRoot={libraryRoot}
                    selectedEvidenceId={selectedEvidenceId}
                  />
                )}
                {sidePaneTab === 'molecules' && (
                  <section className="pdf-current-molecules">
                    <div className="pdf-current-molecules__header">
                      <div><strong>{t('pdf.moleculesHeader')}</strong><span>{t('pdf.moleculesCount', { count: visibleDetections.length })}</span></div>
                      <Button variant="primary" onClick={() => handleDetectPage(true)} disabled={isDetecting || !canDetect}>
                        {isDetecting ? t('pdf.detecting') : t('pdf.detect')}
                      </Button>
                    </div>
                    {visibleDetections.length === 0 ? <p className="pdf-current-molecules__empty">{t('pdf.moleculesEmpty')}</p> : visibleDetections.map((detection, index) => (
                      <button type="button" className="pdf-current-molecule" key={`${detection.esmiles}-${index}`} onClick={() => { setSelectedDetection(index); setEditingDetectionIndex(index) }}>
                        {detection.esmiles ? <RdkitStructure smiles={detection.smiles || detection.esmiles} /> : <span className="pdf-current-molecule__fallback">{t('pdf.structureUnavailable')}</span>}
                        <span className="pdf-current-molecule__meta"><strong>{detection.name || t('pdf.moleculeFallbackName', { index: index + 1 })}</strong><span>{Math.round(detection.moldet_conf * 100)}%</span></span>
                        <MoleculePatentFacts facts={patentFacts} detection={detection} />
                      </button>
                    ))}
                  </section>
                )}
                {sidePaneTab === 'directory' && (
                  <nav className="pdf-directory" aria-label={t('pdf.tabDirectory')}>
                    <div className="pdf-directory__header">
                      <strong>{t('pdf.tabDirectory')}</strong>
                      <Badge tone="neutral">{directoryEntries.length}</Badge>
                    </div>
                    {directoryEntries.length === 0 ? (
                      <p className="pdf-directory__empty">{t('pdf.directoryEmpty')}</p>
                    ) : (
                      <div className="pdf-directory__list">
                        {directoryEntries.map(block => (
                          <button
                            type="button"
                            key={block.evidence_id}
                            className={`pdf-directory__item${block.evidence_id === selectedEvidenceId ? ' is-selected' : ''}`}
                            aria-current={block.evidence_id === selectedEvidenceId ? 'location' : undefined}
                            title={block.content?.trim()}
                            onClick={() => handleDirectorySelect(block)}
                          >
                            <span className="pdf-directory__kind">{block.kind}</span>
                            <span className="pdf-directory__text">{block.content?.trim()}</span>
                            <span className="pdf-directory__page">{block.page}</span>
                          </button>
                        ))}
                      </div>
                    )}
                  </nav>
                )}
              </div>
            </>
          )}
        </aside>
      </div>

      {editingDetectionIndex !== null && visibleDetections[editingDetectionIndex] && (
        <MoleculeEditorDialog
          smiles={visibleDetections[editingDetectionIndex].smiles || visibleDetections[editingDetectionIndex].esmiles}
          name={visibleDetections[editingDetectionIndex].name}
          originalImageUrl={visibleDetections[editingDetectionIndex].mol_img_path
            ? cropImageUrl(doc.doc_id, visibleDetections[editingDetectionIndex].mol_img_path, libraryRoot)
            : null}
          onSave={handleSaveMolecule}
          onClose={() => setEditingDetectionIndex(null)}
        />
      )}

    </div>
  )
})

export default PdfViewer

function compoundLabelKey(value: string): string {
  const cleaned = value
    .normalize('NFKC')
    .trim()
    .replace(/^(?:化合物|compound|cmpd|cpd|mol(?:ecule)?)[#_\-\s]*/i, '')
    .replace(/\s+/g, '')
  const match = /^(\d+[a-z]?)$/i.exec(cleaned)
  return (match?.[1] ?? cleaned).toLowerCase()
}

function measurementLabel(measurement: PatentFactsMeasurement): string {
  const value = measurement.value
  return `${measurement.metric || '—'} ${value.operator} ${value.raw_text} ${value.original_unit}`.trim()
}

function MoleculePatentFacts({
  facts,
  detection,
}: {
  facts: PatentFactsArtifact | null
  detection: ExtractionResult
}) {
  const { t } = useTranslation()
  if (!facts || !detection.name) return null
  const labelKey = compoundLabelKey(detection.name)
  const entries = facts.entries.filter((entry) => entry.label_key === labelKey)
  if (entries.length === 0) return null

  const entryIds = new Set(entries.map((entry) => entry.entry_id))
  const measurements = facts.measurements.filter(
    (measurement) => measurement.compound_entry_id && entryIds.has(measurement.compound_entry_id),
  )
  const evidenceIds = new Set([
    ...entries.flatMap((entry) => entry.evidence_ids),
    ...measurements.flatMap((measurement) => measurement.evidence_ids),
  ])

  return (
    <span className="pdf-current-molecule__facts">
      <span className="pdf-current-molecule__facts-header">
        <strong>{t('pdf.moleculeFactsTitle')}</strong>
        <Badge tone={measurements.length > 0 ? 'success' : 'neutral'}>
          {measurements.length > 0 ? t('pdf.patentFactsMeasured') : t('pdf.moleculeFactsNoMeasurement')}
        </Badge>
      </span>
      {entries.map((entry) => {
        const section = facts.sections.find((item) => item.section_id === entry.section_id)
        return (
          <span className="pdf-current-molecule__fact" key={entry.entry_id}>
            <span>{section?.title || entry.label_raw || entry.label_key}</span>
            {measurements
              .filter((measurement) => measurement.compound_entry_id === entry.entry_id)
              .map((measurement) => (
                <strong key={measurement.measurement_id}>{measurementLabel(measurement)}</strong>
              ))}
          </span>
        )
      })}
      <span className="pdf-current-molecule__facts-meta">
        {t('pdf.moleculeFactsEvidence', { count: evidenceIds.size })}
      </span>
    </span>
  )
}

function LocationHighlight({
  bbox,
  pageInfo,
}: {
  bbox: [number, number, number, number]
  pageInfo: {
    width: number
    height: number
    originalWidth: number
    originalHeight: number
    scale: number
  }
}) {
  const box = pdfToCss(
    bbox,
    pageInfo.originalHeight,
    pageInfo.scale,
    pageInfo.originalWidth,
    pageInfo.width,
  )
  return (
    <div
      aria-label="Deep-linked molecule location"
      style={{
        position: 'absolute',
        top: 0,
        left: '50%',
        width: pageInfo.width,
        height: pageInfo.height,
        transform: 'translateX(-50%)',
        pointerEvents: 'none',
        zIndex: 3,
      }}
    >
      <div
        style={{
          position: 'absolute',
          left: box.x,
          top: box.y,
          width: box.w,
          height: box.h,
          border: '3px solid var(--accent)',
          borderRadius: 4,
          boxShadow: '0 0 0 3px color-mix(in srgb, var(--accent) 24%, transparent)',
        }}
      />
    </div>
  )
}
