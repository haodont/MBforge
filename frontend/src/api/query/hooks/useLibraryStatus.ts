/** React Query hook for library configuration status. */

import { useQuery } from '@tanstack/react-query'
import { getLibraryStatus } from '../../http/library'
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
