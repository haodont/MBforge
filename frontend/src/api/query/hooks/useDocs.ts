/** React Query hooks for the built-in docs Wiki (index + page content). */

import { useQuery } from '@tanstack/react-query'
import { listDocsPages, getDocsPage } from '../../http/docs'
import { queryKeys } from '../keys'

/** The Wiki page index (slug + title list). */
export function useDocsIndex() {
  return useQuery({
    queryKey: queryKeys.docs.index(),
    queryFn: listDocsPages,
  })
}

/** A single Wiki page's rendered markdown content, keyed by slug. */
export function useDocsPage(slug: string | null) {
  return useQuery({
    queryKey: queryKeys.docs.page(slug ?? ''),
    queryFn: () => getDocsPage(slug as string),
    enabled: Boolean(slug),
  })
}
