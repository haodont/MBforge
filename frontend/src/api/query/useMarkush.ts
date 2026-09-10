/** React Query hooks for the Markush review queue. */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  markushDecide,
  markushGetCandidate,
  markushListCandidates,
  markushUpdateCandidate,
  type MarkushDecisionResponse,
  type MarkushListFilters,
  type MarkushListResponse,
  type MarkushUpdatePayload,
} from '@/api/http/markush'
import { queryKeys } from './keys'
import type { MarkushCandidateDetail } from '@/api/http/markush'

/** Query the paged review queue. */
export function useMarkushCandidates(filters: MarkushListFilters) {
  return useQuery<MarkushListResponse>({
    queryKey: queryKeys.markush.list(filters.library_root, { ...filters }),
    queryFn: () => markushListCandidates(filters),
    enabled: Boolean(filters.library_root),
  })
}

/** Fetch one candidate's detail (evidence + decisions). */
export function useMarkushCandidate(
  libraryRoot: string,
  candidateId: string | null,
) {
  return useQuery<MarkushCandidateDetail>({
    queryKey: queryKeys.markush.detail(libraryRoot, candidateId ?? ''),
    queryFn: () => markushGetCandidate(libraryRoot, candidateId as string),
    enabled: Boolean(libraryRoot && candidateId),
  })
}

/** Apply a review decision; on success invalidate the list + detail caches. */
export function useMarkushDecision(libraryRoot: string) {
  const client = useQueryClient()
  return useMutation<
    MarkushDecisionResponse,
    unknown,
    {
      entityId: string
      expectedVersion: number
      action:
        | 'confirm_complete'
        | 'confirm_scaffold'
        | 'confirm_fragment'
        | 'reject'
        | 'reopen'
      reason?: string
    }
  >({
    mutationFn: ({ entityId, expectedVersion, action, reason }) =>
      markushDecide(libraryRoot, entityId, expectedVersion, action, reason ?? ''),
    onSuccess: (_data, vars) => {
      void client.invalidateQueries({
        queryKey: queryKeys.markush.all,
      })
      void client.invalidateQueries({
        queryKey: queryKeys.markush.detail(libraryRoot, vars.entityId),
      })
      // The molecules list counts may change after confirm_complete.
      void client.invalidateQueries({
        queryKey: queryKeys.molecules.all,
      })
    },
  })
}

/** Edit a candidate's editable fields. Invalidates the detail cache. */
export function useMarkushUpdate(libraryRoot: string) {
  const client = useQueryClient()
  return useMutation<MarkushCandidateDetail, unknown, MarkushUpdatePayload>({
    mutationFn: (payload) => markushUpdateCandidate(payload),
    onSuccess: (_data, vars) => {
      void client.invalidateQueries({
        queryKey: queryKeys.markush.all,
      })
      void client.invalidateQueries({
        queryKey: queryKeys.markush.detail(libraryRoot, vars.entity_id),
      })
    },
  })
}

// -- Phase 4 hooks --------------------------------------------------------

import {
  markushCreateMount,
  markushCreateOption,
  markushCreateSite,
  markushDecideMount,
  markushListMounts,
  markushListOptions,
  markushListSites,
  markushUpdateSite,
  type MarkushMount,
  type MarkushOption,
  type MarkushSite,
} from '@/api/http/markush'

export function useMarkushSites(libraryRoot: string, scaffoldId: string | null) {
  return useQuery<MarkushSite[]>({
    queryKey: ['markush', 'sites', libraryRoot, scaffoldId ?? ''],
    queryFn: () => markushListSites(libraryRoot, scaffoldId as string),
    enabled: Boolean(libraryRoot && scaffoldId),
  })
}

export function useMarkushOptions(libraryRoot: string, siteId: string | null) {
  return useQuery<MarkushOption[]>({
    queryKey: ['markush', 'options', libraryRoot, siteId ?? ''],
    queryFn: () => markushListOptions(libraryRoot, siteId as string),
    enabled: Boolean(libraryRoot && siteId),
  })
}

export function useMarkushMounts(
  libraryRoot: string,
  filter: { site_id?: string; scaffold_id?: string; fragment_id?: string } = {},
) {
  return useQuery<MarkushMount[]>({
    queryKey: ['markush', 'mounts', libraryRoot, filter],
    queryFn: () => markushListMounts(libraryRoot, filter),
    enabled: Boolean(libraryRoot),
  })
}

export function useMarkushCreateSite(libraryRoot: string) {
  const client = useQueryClient()
  return useMutation<
    MarkushSite,
    unknown,
    {
      scaffold_id: string
      site_label: string
      atom_map_num: number | null
      attachment_count?: number
      bond_type?: string | null
      source_text?: string
    }
  >({
    mutationFn: (payload) => markushCreateSite(libraryRoot, payload),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ['markush', 'sites', libraryRoot] })
    },
  })
}

export function useMarkushUpdateSite(libraryRoot: string) {
  const client = useQueryClient()
  return useMutation<
    MarkushSite,
    unknown,
    {
      site_id: string
      site_label?: string | null
      atom_map_num?: number | null
      attachment_count?: number | null
      bond_type?: string | null
      source_text?: string | null
    }
  >({
    mutationFn: (payload) => markushUpdateSite(libraryRoot, payload),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ['markush', 'sites', libraryRoot] })
    },
  })
}

export function useMarkushCreateOption(libraryRoot: string) {
  const client = useQueryClient()
  return useMutation<
    MarkushOption,
    unknown,
    {
      site_id: string
      fragment_id?: string | null
      normalized_smiles?: string | null
      definition_text?: string
    }
  >({
    mutationFn: (payload) => markushCreateOption(libraryRoot, payload),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ['markush', 'options', libraryRoot] })
    },
  })
}

export function useMarkushCreateMount(libraryRoot: string) {
  const client = useQueryClient()
  return useMutation<
    MarkushMount,
    unknown,
    {
      site_id: string
      fragment_id: string
      origin?: 'text_definition' | 'proximity' | 'manual'
      confidence?: number | null
      reasons?: string[]
    }
  >({
    mutationFn: (payload) => markushCreateMount(libraryRoot, payload),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ['markush', 'mounts', libraryRoot] })
    },
  })
}

export function useMarkushDecideMount(libraryRoot: string) {
  const client = useQueryClient()
  return useMutation<
    MarkushMount,
    unknown,
    { mount_id: string; action: 'confirm' | 'reject'; reason?: string }
  >({
    mutationFn: ({ mount_id, action, reason }) =>
      markushDecideMount(libraryRoot, mount_id, action, reason ?? ''),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ['markush', 'mounts', libraryRoot] })
    },
  })
}

// -- Phase 6 hooks: Enumeration -------------------------------------------

import {
  markushEnumerationPreview,
  markushEnumerationResults,
  markushEnumerationRun,
  markushGeneratedDecide,
  type EnumerationPreviewResponse,
  type EnumerationRunResponse,
  type GeneratedCandidate,
  type GeneratedDecisionResponse,
  type SiteSelection,
} from "@/api/http/markush"

export function useMarkushEnumerationPreview(libraryRoot: string) {
  return useMutation<
    EnumerationPreviewResponse,
    unknown,
    {
      scaffold_id: string
      selection: SiteSelection[]
    }
  >({
    mutationFn: ({ scaffold_id, selection }) =>
      markushEnumerationPreview(libraryRoot, scaffold_id, selection),
  })
}

export function useMarkushEnumerationRun(libraryRoot: string) {
  const client = useQueryClient()
  return useMutation<
    EnumerationRunResponse,
    unknown,
    {
      scaffold_id: string
      selection: SiteSelection[]
      requested_limit: number
    }
  >({
    mutationFn: ({ scaffold_id, selection, requested_limit }) =>
      markushEnumerationRun(libraryRoot, scaffold_id, selection, requested_limit),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["markush", "enumeration"] })
    },
  })
}

export function useMarkushEnumerationResults(
  libraryRoot: string,
  runId: string | null,
) {
  return useQuery<GeneratedCandidate[]>({
    queryKey: ["markush", "enumeration", "results", libraryRoot, runId ?? ""],
    queryFn: () => markushEnumerationResults(libraryRoot, runId as string),
    enabled: Boolean(libraryRoot && runId),
  })
}

export function useMarkushGeneratedDecide(libraryRoot: string) {
  const client = useQueryClient()
  return useMutation<
    GeneratedDecisionResponse,
    unknown,
    {
      generated_id: string
      action: "confirm" | "reject"
      reason?: string
    }
  >({
    mutationFn: ({ generated_id, action, reason }) =>
      markushGeneratedDecide(libraryRoot, generated_id, action, reason ?? ""),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["markush", "enumeration"] })
      void client.invalidateQueries({ queryKey: queryKeys.molecules.all })
    },
  })
}

