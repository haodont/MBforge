/**
 * Module-level viewer snapshot persistence for the PDF viewer.
 *
 * The original usePdfViewer hook kept its LRU snapshot state inside the
 * module; we extract it here so the navigation/OCR/detections sub-hooks do
 * not need to share a circular dependency just to coordinate persistence.
 */

import { createLruMap } from '@/components/lruMap'
import type { ExtractionResult } from '@/types'
import type { OcrBlock } from '@/api/http/pdf'

export interface PdfViewerSnapshot {
  currentPage: number
  pdfScale: number
  showTextLayer: boolean
  showTextPanel: boolean
  showOcrPanel: boolean
  selectedDetection: number | null
  pageDetections: Array<[number, ExtractionResult[]]>
  ocrBlocks: OcrBlock[]
}

const MAX_VIEWER_SNAPSHOTS = 20

export const viewerSnapshots = createLruMap<string, PdfViewerSnapshot>(MAX_VIEWER_SNAPSHOTS)
