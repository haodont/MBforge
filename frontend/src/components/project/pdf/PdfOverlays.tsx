/**
 * The two bbox overlays drawn over the current page: molecule detections
 * (``MoleculeOverlay``) and OCR layout blocks (``OcrOverlay``).
 *
 * Each is rendered only when the page has been measured and carries rows, so
 * an empty overlay collapses to a fragment exactly as the inline elements did.
 */

import { memo } from 'react'
import type { Dispatch, SetStateAction } from 'react'
import MoleculeOverlay from '@/components/MoleculeOverlay'
import OcrOverlay from '@/components/OcrOverlay'
import type { ExtractionResult } from '@/types'
import type { OcrBlock } from '@/api/http/pdf'
import type { PageRenderInfo } from './usePdfNavigation'

interface Props {
  detections: ExtractionResult[]
  ocrBlocks: OcrBlock[]
  pageInfo: PageRenderInfo | null
  currentPage: number
  selectedDetection: number | null
  selectedOcrIndex: number | null
  isDetecting: boolean
  onMoleculeClick?: (info: {
    page: number
    bbox?: [number, number, number, number] | null
  }) => void
  onRecognize: () => void
  setSelectedDetection: Dispatch<SetStateAction<number | null>>
  setSelectedOcrIndex: Dispatch<SetStateAction<number | null>>
  setSelectedEvidenceId: Dispatch<SetStateAction<string | null>>
}

const PdfOverlays = memo(function PdfOverlays({
  detections,
  ocrBlocks,
  pageInfo,
  currentPage,
  selectedDetection,
  selectedOcrIndex,
  isDetecting,
  onMoleculeClick,
  onRecognize,
  setSelectedDetection,
  setSelectedOcrIndex,
  setSelectedEvidenceId,
}: Props) {
  const pageOverlay = pageInfo && detections.length > 0 ? (
    <MoleculeOverlay
      detections={detections}
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
      onRecognize={onRecognize}
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

  return <>{pageOverlay}{ocrPageOverlay}</>
})

export default PdfOverlays
