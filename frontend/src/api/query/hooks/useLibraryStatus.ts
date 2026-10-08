/** React Query hooks for library configuration status. */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { configureLibrary, getLibraryStatus } from '../../http/library'
import { queryKeys } from '../keys'

/**
 * Read library status (configured, root, doc_count).
 *
 * Stale time is 60 s; this data only changes when the user configures
 * a different library root via the Welcome / Settings screen.
 */
export function useLibraryStatus() {
  return useQuery({
    queryKey: queryKeys.library.status(),
    queryFn: getLibraryStatus,
    staleTime: 60_000,
  })
}

/**
 * Point the backend at a library root.
 *
 * Returns the raw `{ success, root, error }` payload so the caller can decide
 * how to surface a soft failure. On success the cached status is invalidated so
 * the configured root is refetched.
 */
export function useConfigureLibrary() {
  const qc = useQueryClient()

  return useMutation({
    mutationFn: (root: string) => configureLibrary(root),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: queryKeys.library.all })
    },
  })
}
