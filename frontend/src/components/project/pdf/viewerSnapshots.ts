/**
 * Module-level viewer snapshot persistence for the PDF viewer.
 *
 * The original usePdfViewer hook kept its LRU snapshot state inside the
 * module; we extract it here so the navigation/OCR/detections sub-hooks do
 * not need to share a circular dependency just to coordinate persistence.
 *
 * A small, reload-safe subset (position, zoom and overlay toggles) is also
 * mirrored into ``localStorage`` so reopening the app resumes the same page
 * instead of restarting at page 1.
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

/** Reload-safe subset of the viewer state. */
export interface PersistedViewerState {
  currentPage: number
  pdfScale: number
  showTextLayer: boolean
  showMoleculeOverlay: boolean
  showOcrOverlay: boolean
  continuousMode: boolean
}

const MAX_VIEWER_SNAPSHOTS = 20
const PERSIST_PREFIX = 'mbforge.pdf.viewer.'

export const viewerSnapshots = createLruMap<string, PdfViewerSnapshot>(MAX_VIEWER_SNAPSHOTS)

export function loadPersistedViewerState(key: string): PersistedViewerState | null {
  if (typeof window === 'undefined') return null
  try {
    const raw = window.localStorage.getItem(`${PERSIST_PREFIX}${key}`)
    if (!raw) return null
    const data = JSON.parse(raw) as Partial<PersistedViewerState>
    if (
      typeof data.currentPage !== 'number'
      || typeof data.pdfScale !== 'number'
      || typeof data.showTextLayer !== 'boolean'
      || typeof data.showMoleculeOverlay !== 'boolean'
      || typeof data.showOcrOverlay !== 'boolean'
      || typeof data.continuousMode !== 'boolean'
    ) {
      return null
    }
    return {
      currentPage: Math.max(1, Math.round(data.currentPage)),
      pdfScale: Math.min(5, Math.max(0.5, data.pdfScale)),
      showTextLayer: data.showTextLayer,
      showMoleculeOverlay: data.showMoleculeOverlay,
      showOcrOverlay: data.showOcrOverlay,
      continuousMode: data.continuousMode,
    }
  } catch {
    return null
  }
}

export function savePersistedViewerState(key: string, state: PersistedViewerState): void {
  if (typeof window === 'undefined') return
  try {
    window.localStorage.setItem(`${PERSIST_PREFIX}${key}`, JSON.stringify(state))
  } catch {
    // Quota / privacy-mode failures must not break reading.
  }
}
