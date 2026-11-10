/** React Query hooks for the local model-service status. */

import { useQuery } from '@tanstack/react-query'
import { sidecarStatus } from '@/api/http/sidecar'
import { queryKeys } from '../keys'

/**
 * Read the model-service health snapshot (uptime, restart count, last error).
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
