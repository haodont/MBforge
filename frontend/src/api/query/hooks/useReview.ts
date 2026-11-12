/** React Query hooks for the human-review queue. */

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  reviewQueue,
  reviewStats,
  reviewDecide,
  reviewDecideFiltered,
  reviewClear,
  reviewHistory,
  reviewItem,
  type ReviewAction,
  type ReviewKind,
  type ReviewDecisionItem,
  type ReviewQueueItem,
  type ReviewStatus,
} from '../../http/review'
import { queryKeys } from '../keys'

export interface ReviewFilters {
  kind?: ReviewKind
  status?: ReviewStatus
  docId?: string
  page?: number
  pageSize?: number
}

/** Paginated review queue for the current filter set. */
export function useReviewQueue(libraryRoot: string, filters: ReviewFilters) {
  return useQuery({
    queryKey: queryKeys.review.queue(libraryRoot, filters),
    queryFn: () => reviewQueue(libraryRoot, filters),
    enabled: Boolean(libraryRoot),
  })
}

/** Review counts by kind/status plus pending total. */
export function useReviewStats(libraryRoot: string) {
  return useQuery({
    queryKey: queryKeys.review.stats(libraryRoot),
    queryFn: () => reviewStats(libraryRoot),
    enabled: Boolean(libraryRoot),
  })
}

/** One queue item by id, for a link that names it directly.
 *
 * A link may point at an item that is not on the first page of the current
 * filter set; the queue query alone cannot open it. The kind is the item's own
 * and defaults to ``designation_unbound``, the kind a shared link usually names.
 */
export function useReviewItem(libraryRoot: string, kind: ReviewKind | null, id: string | null) {
  return useQuery({
    queryKey: [...queryKeys.review.all, 'item', libraryRoot, kind ?? '', id ?? ''],
    queryFn: () => reviewItem(libraryRoot, kind ?? 'designation_unbound', id as string),
    enabled: Boolean(libraryRoot) && Boolean(id),
  })
}

/** Submit a confirm/reject/reopen decision and refresh the queue + stats. */
export function useReviewDecide() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (args: {
      libraryRoot: string
      items: ReviewDecisionItem[]
      action: ReviewAction
      reason?: string
    }) => reviewDecide(args.libraryRoot, args.items, args.action, args.reason ?? ''),
    onSuccess: (_data, variables) => {
      void qc.invalidateQueries({ queryKey: queryKeys.review.all })
      // A decision on any kind can rewrite the molecule and document
      // projections (a corrected structure, a bound reading, an AI proposal),
      // so both caches are refreshed uniformly.
      void qc.invalidateQueries({ queryKey: queryKeys.documents.all })
      void qc.invalidateQueries({ queryKey: queryKeys.molecules.all })
      for (const item of variables.items) {
        void qc.invalidateQueries({
          queryKey: queryKeys.review.history(variables.libraryRoot, item.id),
        })
      }
    },
  })
}

/** Decide a whole filtered batch (all text-level proposals / one document). */
export function useReviewDecideFiltered() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (args: {
      libraryRoot: string
      filter: { kind?: ReviewKind; docId?: string; targetKind?: string }
      action: ReviewAction
      reason?: string
    }) =>
      reviewDecideFiltered(
        args.libraryRoot,
        args.filter,
        args.action,
        args.reason ?? '',
      ),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: queryKeys.review.all })
    },
  })
}

/** Empty the entire review center and refresh the queue + stats. */
export function useReviewClearAll() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (libraryRoot: string) => reviewClear(libraryRoot),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: queryKeys.review.all })
    },
  })
}

/** Decision history for one reviewed entity. */
export function useReviewHistory(libraryRoot: string, entityId: string | null) {
  return useQuery({
    queryKey: queryKeys.review.history(libraryRoot, entityId ?? ''),
    queryFn: () => reviewHistory(libraryRoot, entityId as string),
    enabled: Boolean(libraryRoot) && Boolean(entityId),
    select: (data) => data.history,
  })
}

/** Stable helper for consumers that keep a plain item list (legacy state). */
const EMPTY_QUEUE: ReviewQueueItem[] = []
export function toQueueItems(items: ReviewQueueItem[] | undefined): ReviewQueueItem[] {
  return Array.isArray(items) ? items : EMPTY_QUEUE
}
