/** React Query hook for the OS common-directory shortcuts (FolderPicker). */

import { useQuery } from '@tanstack/react-query'
import { getCommonDirs } from '@/api/http/project'
import { queryKeys } from '../keys'

/**
 * Folder shortcuts shown by FolderPicker. In web mode this is a static
 * (empty) list, so the value is cached for the whole session.
 */
export function useCommonDirs() {
  return useQuery({
    queryKey: queryKeys.dirs.common(),
    queryFn: getCommonDirs,
    staleTime: Infinity,
  })
}
