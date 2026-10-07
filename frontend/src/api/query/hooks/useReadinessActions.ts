/** React Query hooks for the readiness probe / demo-run actions. */

import { useMutation, useQueryClient } from '@tanstack/react-query'
import {
  readinessDemoRun,
  readinessProbeLlm,
  type DemoRunResult,
  type ProbeLlmResult,
} from '@/api/http/readiness'
import { queryKeys } from '../keys'

/** Probe the configured LLM endpoint through the agent sidecar. */
export function useReadinessProbeLlm() {
  return useMutation<ProbeLlmResult>({
    mutationFn: () => readinessProbeLlm(),
  })
}

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
