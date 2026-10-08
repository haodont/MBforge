/** React Query hooks for the molecule library, chem, and analytics APIs. */

import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import {
  molAdminBulkDelete,
  molAdminBulkUpdateStatus,
  molAdminGet,
  molAdminListPage,
  molAdminUpdate,
} from '@/api/http/molecule_admin'
import type {
  MoleculeBulkStatusResult,
  MoleculeListPage,
  MoleculeListParams,
} from '@/api/http/molecule_admin'
import { moleculeByLocation, moleculeCorrections } from '@/api/http/molecule_store'
import type { MoleculeCorrection, MoleculeLocationMatch } from '@/api/http/molecule_store'
import {
  chemDescriptors,
  molAddRelation,
  molAssignCluster,
  molDedupBatch,
  molDeleteRelation,
  molFindAnalogsWithActivity,
  molFindByMolecule,
  molGetClusterMembers,
  molGetStats,
  molListClusters,
  molRemoveFromCluster,
  molSearchSubstructure,
  smilesToRdkitSvg,
  validateSmiles,
} from '@/api/http/molecule_chem'
import type {
  AnalogWithActivity,
  ChemDescriptors,
  ClusterInfo,
  DedupResult,
  MoleculeRelation,
  RelationStats,
  SubstructureMatch,
  ValidateResponse,
} from '@/api/http/molecule_chem'
import { updateMoleculeEvidence } from '@/api/http/library'
import { queryKeys } from '../keys'
import type { MoleculeRecord } from '@/types'

// ── Reads ────────────────────────────────────────────────────────────

/**
 * Server-side paginated, filtered, sorted molecule listing.
 *
 * Previous-page data is kept while the next page loads so the table does
 * not blank out between fetches.
 */
export function useMoleculePage(
  libraryRoot: string | null,
  params: MoleculeListParams,
) {
  return useQuery<MoleculeListPage>({
    queryKey: queryKeys.molecules.page(libraryRoot ?? '', params),
    queryFn: () => molAdminListPage(libraryRoot as string, params),
    enabled: Boolean(libraryRoot),
    placeholderData: keepPreviousData,
  })
}

/** A single molecule record by id. */
export function useMolecule(libraryRoot: string | null, molId: string | null) {
  return useQuery<MoleculeRecord | null>({
    queryKey: queryKeys.molecules.detail(libraryRoot ?? '', molId ?? ''),
    queryFn: () => molAdminGet(libraryRoot as string, molId as string),
    enabled: Boolean(libraryRoot && molId),
  })
}

/** Molecules whose structure sits at a given PDF location. */
export function useMoleculesByLocation(
  libraryRoot: string | null,
  docId: string | null,
  page: number,
  bbox: [number, number, number, number] | null,
) {
  return useQuery<MoleculeLocationMatch[]>({
    queryKey: queryKeys.molecules.byLocation(libraryRoot ?? '', docId ?? '', page, bbox),
    queryFn: () =>
      moleculeByLocation(
        libraryRoot as string,
        docId as string,
        page,
        bbox as [number, number, number, number],
      ),
    enabled: Boolean(libraryRoot && docId && bbox),
  })
}

/** Correction audit trail for one molecule. */
export function useMoleculeCorrections(
  libraryRoot: string | null,
  molId: string | null,
) {
  return useQuery<MoleculeCorrection[]>({
    queryKey: queryKeys.molecules.corrections(libraryRoot ?? '', molId ?? ''),
    queryFn: () => moleculeCorrections(libraryRoot as string, molId as string),
    enabled: Boolean(libraryRoot && molId),
  })
}

/** Physicochemical descriptors for a SMILES string. */
export function useChemDescriptors(smiles: string | null | undefined) {
  return useQuery<ChemDescriptors>({
    queryKey: queryKeys.molecules.descriptors(smiles ?? ''),
    queryFn: () => chemDescriptors(smiles as string),
    enabled: Boolean(smiles),
  })
}

/** RDKit-backed SMILES validation (canonical form + issues). */
export function useValidateSmiles(smiles: string | null | undefined) {
  return useQuery<ValidateResponse>({
    queryKey: queryKeys.molecules.validation(smiles ?? ''),
    queryFn: () => validateSmiles(smiles as string),
    enabled: Boolean(smiles),
  })
}

/** Server-rendered RDKit structure image (an SVG string). */
export function useSmilesToRdkitSvg(
  smiles: string | null | undefined,
  width = 360,
  height = 240,
) {
  return useQuery<string>({
    queryKey: queryKeys.molecules.svg(smiles ?? '', width, height),
    queryFn: () => smilesToRdkitSvg(smiles as string, width, height),
    enabled: Boolean(smiles),
  })
}

/** All molecule clusters in the library. */
export function useMoleculeClusters() {
  return useQuery<ClusterInfo[]>({
    queryKey: queryKeys.molecules.clusters(),
    queryFn: () => molListClusters(),
  })
}

/** The member list of a single cluster. */
export function useClusterMembers(clusterId: string | null) {
  return useQuery<ClusterInfo>({
    queryKey: queryKeys.molecules.clusterMembers(clusterId ?? ''),
    queryFn: () => molGetClusterMembers(clusterId as string),
    enabled: Boolean(clusterId),
  })
}

/** Aggregate relation statistics. */
export function useRelationStats() {
  return useQuery<RelationStats>({
    queryKey: queryKeys.molecules.relationStats(),
    queryFn: () => molGetStats(),
  })
}

/** Relations anchored at a single molecule. */
export function useMoleculeRelations(molId: string | null) {
  return useQuery<MoleculeRelation[]>({
    queryKey: queryKeys.molecules.relations(molId ?? ''),
    queryFn: () => molFindByMolecule(molId as string),
    enabled: Boolean(molId),
  })
}

/** Substructure search results for a query SMILES. */
export function useSubstructureSearch(query: string | null, threshold: number) {
  return useQuery<SubstructureMatch[]>({
    queryKey: queryKeys.molecules.substructure(query ?? '', threshold),
    queryFn: () => molSearchSubstructure(query as string, threshold),
    enabled: Boolean(query),
  })
}

/** Activity-annotated analogs of a reference molecule. */
export function useAnalogSearch(molId: string | null, minSimilarity: number) {
  return useQuery<AnalogWithActivity[]>({
    queryKey: queryKeys.molecules.analogs(molId ?? '', minSimilarity),
    queryFn: () => molFindAnalogsWithActivity(molId as string, minSimilarity),
    enabled: Boolean(molId),
  })
}

// ── Writes ───────────────────────────────────────────────────────────

/** Persist an edited molecule record. */
export function useUpdateMolecule() {
  const qc = useQueryClient()

  return useMutation<boolean, unknown, { libraryRoot: string; record: MoleculeRecord }>({
    mutationFn: ({ libraryRoot, record }) => molAdminUpdate(libraryRoot, record),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: queryKeys.molecules.all })
    },
  })
}

/** Bulk-delete molecules. */
export function useBulkDeleteMolecules() {
  const qc = useQueryClient()

  return useMutation<number, unknown, { libraryRoot: string; molIds: string[] }>({
    mutationFn: ({ libraryRoot, molIds }) => molAdminBulkDelete(libraryRoot, molIds),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: queryKeys.molecules.all })
    },
  })
}

/** Bulk-update the status of several molecules. */
export function useBulkUpdateMoleculeStatus() {
  const qc = useQueryClient()

  return useMutation<
    MoleculeBulkStatusResult,
    unknown,
    { libraryRoot: string; molIds: string[]; status: string }
  >({
    mutationFn: ({ libraryRoot, molIds, status }) =>
      molAdminBulkUpdateStatus(libraryRoot, molIds, status),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: queryKeys.molecules.all })
    },
  })
}

/** Attach a molecule identity (name + SMILES) to an evidence row. */
export function useUpdateMoleculeEvidence() {
  const qc = useQueryClient()

  return useMutation<
    { success: boolean; evidence_id: string },
    unknown,
    { docId: string; evidenceId: string; name: string; smiles: string }
  >({
    mutationFn: ({ docId, evidenceId, name, smiles }) =>
      updateMoleculeEvidence(docId, evidenceId, name, smiles),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: queryKeys.molecules.all })
      void qc.invalidateQueries({ queryKey: queryKeys.documents.all })
    },
  })
}

/** Assign a molecule to a cluster. */
export function useAssignCluster() {
  const qc = useQueryClient()

  return useMutation<number, unknown, { molId: string; clusterId: string }>({
    mutationFn: ({ molId, clusterId }) => molAssignCluster(molId, clusterId),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: queryKeys.molecules.clusters() })
      void qc.invalidateQueries({ queryKey: queryKeys.molecules.all })
    },
  })
}

/** Remove a molecule from a cluster. */
export function useRemoveFromCluster() {
  const qc = useQueryClient()

  return useMutation<boolean, unknown, { molId: string; clusterId: string }>({
    mutationFn: ({ molId, clusterId }) => molRemoveFromCluster(molId, clusterId),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: queryKeys.molecules.clusters() })
      void qc.invalidateQueries({ queryKey: queryKeys.molecules.all })
    },
  })
}

/** Create a molecule relation. */
export function useAddRelation() {
  const qc = useQueryClient()

  return useMutation<
    number,
    unknown,
    {
      molAId: string
      molBId: string
      relationType: string
      score?: number
    }
  >({
    mutationFn: ({ molAId, molBId, relationType, score }) =>
      molAddRelation(molAId, molBId, relationType, score),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: queryKeys.molecules.all })
    },
  })
}

/** Delete a molecule relation. */
export function useDeleteRelation() {
  const qc = useQueryClient()

  return useMutation<boolean, unknown, { id: number }>({
    mutationFn: ({ id }) => molDeleteRelation(id),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: queryKeys.molecules.all })
    },
  })
}

/** Run duplicate detection over a batch of molecules. */
export function useDedupBatch() {
  const qc = useQueryClient()

  return useMutation<
    DedupResult,
    unknown,
    { newMols: Array<[string, string]>; sameAsThreshold?: number }
  >({
    mutationFn: ({ newMols, sameAsThreshold }) => molDedupBatch(newMols, sameAsThreshold),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: queryKeys.molecules.all })
    },
  })
}
