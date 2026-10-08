/** React Query hooks for backend settings (load + save) and About data. */

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  exportSettings,
  fetchBuildInfo,
  getLlmEnvConfig,
  getSettings,
  saveSettings,
  testLlmConnection,
} from '../../http/settings'
import type { BuildInfo, LlmProbeOverride } from '../../http/settings'
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

/**
 * Read the resolved LLM env config (provider / base_url / model) for display.
 *
 * This only reads the persisted config; it does not perform a network probe.
 * Pass `enabled = false` to defer the read (e.g. cards without a Test button).
 */
export function useLlmEnvConfig(enabled = true) {
  return useQuery({
    queryKey: queryKeys.settings.llmEnv(),
    queryFn: getLlmEnvConfig,
    enabled,
  })
}

/**
 * Probe the configured (or supplied, unsaved) LLM endpoint through the
 * sidecar. The probe result is written into the env-config cache so the
 * status badge reflects it without a second round-trip.
 */
export function useTestLlmConnection() {
  const qc = useQueryClient()

  return useMutation({
    mutationFn: (override: LlmProbeOverride) => testLlmConnection(override),
    onSuccess: (data) => {
      qc.setQueryData(queryKeys.settings.llmEnv(), data)
    },
  })
}

/** Read the static build info (version + platform) for the About section. */
export function useBuildInfo(enabled = true) {
  return useQuery<BuildInfo>({
    queryKey: queryKeys.about.buildInfo(),
    queryFn: fetchBuildInfo,
    enabled,
    staleTime: Infinity,
  })
}

/** Export the current settings as a downloadable JSON file. */
export function useExportSettings() {
  return useMutation({
    mutationFn: (targetPath: string) => exportSettings(targetPath),
  })
}
