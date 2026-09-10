/** React Query hooks for the human-review queue. */

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  reviewQueue,
  reviewStats,
  reviewDecide,
  reviewClear,
  reviewHistory,
  type ReviewAction,
  type ReviewKind,
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

/** Submit a confirm/reject/reopen decision and refresh the queue + stats. */
export function useReviewDecide() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (args: {
      libraryRoot: string
      items: Array<{ kind: ReviewKind; id: string }>
      action: ReviewAction
      reason?: string
    }) => reviewDecide(args.libraryRoot, args.items, args.action, args.reason ?? ''),
    onSuccess: (_data, variables) => {
      void qc.invalidateQueries({ queryKey: queryKeys.review.all })
      for (const item of variables.items) {
        void qc.invalidateQueries({
          queryKey: queryKeys.review.history(variables.libraryRoot, item.id),
        })
      }
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