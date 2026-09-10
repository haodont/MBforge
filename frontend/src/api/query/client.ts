/** @tanstack/react-query client factory. */

import { QueryClient } from '@tanstack/react-query'

/** Default stale time: 30 s.  Library data changes infrequently,
 *  so there is no need to refetch on every mount. */
const DEFAULT_STALE_TIME = 5 * 60_000

/** Garbage-collection time: 5 min.  After all observers unmount, the
 *  cached data survives for GC-time before being evicted. */
const DEFAULT_GC_TIME = 30 * 60_000

/**
 * Shared query client for the MBForge application.
 *
 * - `staleTime: 30s` — data is "fresh" for 30 seconds
 * - `gcTime: 5min` — unused cache entries survive 5 minutes
 * - `refetchOnWindowFocus: false` — library data is not live-edited by others
 * - `retry: 1` — one automatic retry on transient network errors
 */
export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: DEFAULT_STALE_TIME,
      gcTime: DEFAULT_GC_TIME,
      refetchOnWindowFocus: false,
      retry: 1,
    },
  },
})

/**
 * Factory for test environments.
 * Returns a fresh `QueryClient` with retries disabled so tests do not
 * hang on intentionally-failed queries.
 */
export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
        staleTime: DEFAULT_STALE_TIME,
        gcTime: DEFAULT_GC_TIME,
        refetchOnWindowFocus: false,
      },
    },
  })
}
