/** PDF document overlay — feeds the viewer's OCR panel and molecule overlay. */

import { httpPost, invokeWithError } from './_utils'
import { ErrorCode } from '@/utils/errors'
import type { ExtractionResult } from '@/types'

export interface OcrBlock {
  evidence_id: string
  page: number
  block_type: string
  /** Original producer label (for example `bib` or `noise`). */
  kind?: string
  bbox: [number, number, number, number]
  content: string | null
  index: number
  angle: number
}

/** Response of ``POST /api/v1/pdf/document-overlay``.
 *
 * ``pages`` is keyed by the 1-based visual page (JSON object keys are always
 * strings); ``source`` describes the molecule side of the payload. */
export interface DocumentOverlayResponse {
  success: boolean
  path: string
  from_cache: boolean
  blocks: OcrBlock[]
  pages: Record<string, ExtractionResult[]>
  count: number
  source: 'source_evidence' | 'empty'
}

/** One SQL-backed request covering both page overlays of a document. */
export async function getDocumentOverlay(params: {
  libraryRoot: string
  docId: string
  path: string
}): Promise<DocumentOverlayResponse> {
  return invokeWithError(
    () =>
      httpPost<DocumentOverlayResponse>('/api/v1/pdf/document-overlay', {
        library_root: params.libraryRoot,
        doc_id: params.docId,
        path: params.path,
      }),
    ErrorCode.PdfParse,
  )
}
