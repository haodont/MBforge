/** React Query hooks for PDF molecule detection / OCR flows. */

import { useMutation, useQueryClient } from '@tanstack/react-query'

import {
  clearDetectionCacheForDoc,
  extractPdfMolecules,
  savePageDetections,
} from '@/api/http/detection_cache'
import type { ExtractionResult } from '@/types'
import { queryKeys } from '../keys'

/**
 * Run MoldDet + MolParser on a single PDF page (no cache read).
 *
 * The result set is owned by the caller (the viewer façade), so this mutation
 * performs no cache invalidation.
 */
export function useExtractPdfMolecules() {
  return useMutation<
    ExtractionResult[],
    unknown,
    { libraryRoot: string; docId: string; page: number }
  >({
    mutationFn: ({ libraryRoot, docId, page }) =>
      extractPdfMolecules({ libraryRoot, docId, page }),
  })
}

/**
 * Persist detection results so later PDF opens can reuse the cache.
 *
 * The document overlay is derived from the same per-page detection rows, so
 * its cache is invalidated to stay coherent on the next open.
 */
export function useSavePageDetections() {
  const qc = useQueryClient()

  return useMutation({
    mutationFn: ({
      libraryRoot,
      docId,
      page,
      results,
    }: {
      libraryRoot: string
      docId: string
      page: number
      results: ExtractionResult[]
    }) => savePageDetections(libraryRoot, docId, page, results),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: queryKeys.pdf.all })
    },
  })
}

/** Wipe the detection cache for a single document. */
export function useClearDetectionCacheForDoc() {
  const qc = useQueryClient()

  return useMutation({
    mutationFn: ({ libraryRoot, docId }: { libraryRoot: string; docId: string }) =>
      clearDetectionCacheForDoc(libraryRoot, docId),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: queryKeys.pdf.all })
    },
  })
}
