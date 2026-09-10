/** React Query hooks for backend settings (load + save). */

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { getSettings, saveSettings } from '../../http/settings'
import { queryKeys } from '../keys'

/** Load the backend settings snapshot (used to seed the Settings form). */
export function useSettings() {
  return useQuery({
    queryKey: queryKeys.settings.get(),
    queryFn: getSettings,
  })
}

/** Persist the full settings payload and refresh the cached snapshot. */
export function useSaveSettings() {
  const qc = useQueryClient()

  return useMutation({
    mutationFn: (settings: Record<string, unknown>) => saveSettings(settings),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: queryKeys.settings.all })
    },
  })
}
