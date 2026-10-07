/** React Query hook for the server-managed config directory path. */

import { useQuery } from '@tanstack/react-query'
import { getConfigDir } from '@/api/http/settings'
import { queryKeys } from '../keys'

/**
 * Read the config directory path.
 *
 * Fetched lazily (`enabled: false`) — the Settings page triggers it on demand
 * when the user asks to open the config folder.
 */
export function useConfigDir() {
  return useQuery({
    queryKey: queryKeys.settings.configDir(),
    queryFn: getConfigDir,
    enabled: false,
  })
}
