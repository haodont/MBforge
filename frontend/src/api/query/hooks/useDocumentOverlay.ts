/** React Query hook for the PDF document overlay request. */

import { useQuery } from '@tanstack/react-query'

import { getDocumentOverlay } from '@/api/http/pdf'
import type { DocumentOverlayResponse } from '@/api/http/pdf'
import { queryKeys } from '../keys'

/**
 * The single SQL-backed request that primes both the OCR layout blocks and
 * every page's molecule bboxes for one document.
 *
 * The request is keyed per document (library root + doc id + path) so page
 * turns and re-renders never refetch; callers disable it while a warm
 * snapshot already holds the overlay.
 */
export function useDocumentOverlay(params: {
  libraryRoot: string
  docId: string
  path: string
  enabled?: boolean
}) {
  const { libraryRoot, docId, path, enabled = true } = params

  return useQuery<DocumentOverlayResponse>({
    queryKey: queryKeys.pdf.overlay(libraryRoot, docId, path),
    queryFn: () => getDocumentOverlay({ libraryRoot, docId, path }),
    enabled: enabled && Boolean(libraryRoot && docId && path),
  })
}
