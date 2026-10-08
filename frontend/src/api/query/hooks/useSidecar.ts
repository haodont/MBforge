/** React Query hooks for the Python sidecar process lifecycle. */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { sidecarRestart, sidecarStatus } from '@/api/http/sidecar'
import { queryKeys } from '../keys'

/**
 * Read the sidecar health snapshot (uptime, restart count, last error).
 *
 * Pass `enabled = false` for an on-demand probe: the query stays idle until
 * `refetch()` is called (e.g. the Settings "Test connection" button).
 */
export function useSidecarStatus(enabled = true) {
  return useQuery({
    queryKey: queryKeys.sidecar.status(),
    queryFn: sidecarStatus,
    enabled,
  })
}

/** Force-restart the sidecar; the health snapshot is refreshed on success. */
export function useSidecarRestart() {
  const qc = useQueryClient()

  return useMutation({
    mutationFn: sidecarRestart,
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: queryKeys.sidecar.all })
    },
  })
}
