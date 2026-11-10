/** React Query hooks for the readiness demo-run action. */

import { useMutation, useQueryClient } from '@tanstack/react-query'
import { readinessDemoRun, type DemoRunResult } from '@/api/http/readiness'
import { queryKeys } from '../keys'

/** Enqueue the readiness smoke-test document through the pipeline. */
export function useReadinessDemoRun() {
  const qc = useQueryClient()

  return useMutation<DemoRunResult>({
    mutationFn: () => readinessDemoRun(),
    onSuccess: () => {
      // A demo run inserts a pipeline task, so the ingest queue is stale.
      void qc.invalidateQueries({ queryKey: queryKeys.ingest.all })
    },
  })
}
