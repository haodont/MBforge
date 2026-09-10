/** React Query hooks for readiness diagnostics. */

import { useQuery } from '@tanstack/react-query'
import { readinessSummary, type ReadinessSummary } from '../../http/readiness'
import { queryKeys } from '../keys'

/** Aggregate readiness summary across library, DB, models, LLM and OCR. */
export function useReadinessSummary() {
  return useQuery<ReadinessSummary>({
    queryKey: queryKeys.readiness.summary(),
    queryFn: readinessSummary,
    staleTime: 15_000,
    refetchOnWindowFocus: false,
  })
}