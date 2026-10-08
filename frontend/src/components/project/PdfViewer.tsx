import { forwardRef, useCallback, useImperativeHandle, useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import PdfCanvas from '@/components/PdfCanvas'
import ScrollColumn from '../ui/ScrollColumn'
import { LoadingState } from '../ui/LoadingState'
import type { DocumentEntry, ExtractionResult } from '@/types'
import { usePdfViewer } from './pdf/usePdfViewer'
import { usePdfSidebarState } from './pdf/usePdfSidebarState'
import { usePdfDeepLink } from './pdf/usePdfDeepLink'
import PdfOverlays from './pdf/PdfOverlays'
import PdfSidebar from './pdf/PdfSidebar'
import PdfFloatingControls from './pdf/PdfFloatingControls'
import PdfContinuousView from './pdf/PdfContinuousView'
import LocationHighlight from './pdf/LocationHighlight'
import MoleculeEditorDialog from '@/components/molecule/MoleculeEditorDialog'
import { cropImageUrl } from '@/api/http/library'
import { useDocumentPatentFacts } from '@/api/query/hooks'

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
  initialEvidenceId?: string
  viewerKey?: string
}

const PdfViewer = forwardRef<PdfViewerHandle, Props>(function PdfViewer(
  { doc, libraryRoot, onClose: _onClose, onMoleculeClick, initialPage, initialBbox, initialEvidenceId, viewerKey },
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
  const {
    isResultPaneCollapsed, setIsResultPaneCollapsed,
    sourcePaneWidth,
    sidePaneTab, setSidePaneTab,
    selectedEvidenceId, setSelectedEvidenceId,
    editingDetectionIndex, setEditingDetectionIndex,
    continuousMode, toggleContinuousMode,
  } = usePdfSidebarState({ pageInfo })
  const { data: patentFactsResult } = useDocumentPatentFacts(doc.doc_id, libraryRoot)
  const patentFacts = patentFactsResult?.ok ? patentFactsResult.data : null
  const pdfCanvasStyle = useMemo(() => ({
    background: '#fff',
    boxShadow: 'var(--shadow-md)',
  }), [])
  const openTextPanel = useCallback(() => setShowTextPanel(true), [setShowTextPanel])
  const handleContinuousPageChange = useCallback((page: number) => setCurrentPage(page), [setCurrentPage])

  // 覆盖层读源：文档打开时一次性加载全文 bbox（流水线 v2 证据 ∪ 交互识别写入的
  // molecule_detections，后端逐页去重，含低置信/被拒候选，框颜色编码置信度）；
  // MoleculeOverlay 自身保留 bbox 有效性过滤。
  const visibleDetections = currentDetections

  usePdfDeepLink({
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
  })

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
                  overlay={(
                    <PdfOverlays
                      detections={visibleDetections}
                      ocrBlocks={ocrBlocks}
                      pageInfo={pageInfo}
                      currentPage={currentPage}
                      selectedDetection={selectedDetection}
                      selectedOcrIndex={selectedOcrIndex}
                      isDetecting={isDetecting}
                      onMoleculeClick={onMoleculeClick}
                      onRecognize={handleRecognizePage}
                      setSelectedDetection={setSelectedDetection}
                      setSelectedOcrIndex={setSelectedOcrIndex}
                      setSelectedEvidenceId={setSelectedEvidenceId}
                    />
                  )}
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
                <PdfOverlays
                  detections={visibleDetections}
                  ocrBlocks={ocrBlocks}
                  pageInfo={pageInfo}
                  currentPage={currentPage}
                  selectedDetection={selectedDetection}
                  selectedOcrIndex={selectedOcrIndex}
                  isDetecting={isDetecting}
                  onMoleculeClick={onMoleculeClick}
                  onRecognize={handleRecognizePage}
                  setSelectedDetection={setSelectedDetection}
                  setSelectedOcrIndex={setSelectedOcrIndex}
                  setSelectedEvidenceId={setSelectedEvidenceId}
                />
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
            onToggleContinuous={toggleContinuousMode}
          />
        </div>

        {/* 右侧：当前页 SQL 证据与分子；事实证据显示在分子卡片内 */}
        <PdfSidebar
          docId={doc.doc_id}
          libraryRoot={libraryRoot}
          currentPage={currentPage}
          isResultPaneCollapsed={isResultPaneCollapsed}
          setIsResultPaneCollapsed={setIsResultPaneCollapsed}
          sidePaneTab={sidePaneTab}
          setSidePaneTab={setSidePaneTab}
          selectedEvidenceId={selectedEvidenceId}
          detections={visibleDetections}
          isDetecting={isDetecting}
          canDetect={canDetect}
          patentFacts={patentFacts}
          onDetect={() => handleDetectPage(true)}
          setSelectedDetection={setSelectedDetection}
          setEditingDetectionIndex={setEditingDetectionIndex}
        />
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
