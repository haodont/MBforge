/** React Query hooks for the molecule library and chem APIs. */

import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import {
  molAdminAdd,
  molAdminBulkDelete,
  molAdminBulkUpdateStatus,
  molAdminGet,
  molAdminListPage,
  molAdminSearchBySmiles,
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
  chemValidateSmiles,
  smilesToRdkitSvg,
  validateSmiles,
} from '@/api/http/molecule_chem'
import type {
  ChemDescriptors,
  SmilesValidation,
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

// ── SMILES validation / create (imperative dialog flows) ─────────────

/**
 * Validate a SMILES string through the RDKit backend.
 *
 * Exposed as a mutation because the Add-molecule dialog validates on each
 * keystroke and again on submit — the result drives local form state rather
 * than a rendered cache entry.
 */
export function useChemValidateSmiles() {
  return useMutation<SmilesValidation, unknown, string>({
    mutationFn: (smiles) => chemValidateSmiles(smiles),
  })
}

/** Exact-SMILES lookup used to warn about duplicates before insert. */
export function useMoleculeSearchBySmiles() {
  return useMutation<
    MoleculeRecord | null,
    unknown,
    { libraryRoot: string; smiles: string }
  >({
    mutationFn: ({ libraryRoot, smiles }) => molAdminSearchBySmiles(libraryRoot, smiles),
  })
}

/** Insert a new molecule record; the listing caches are refreshed. */
export function useAddMolecule() {
  const qc = useQueryClient()

  return useMutation({
    mutationFn: ({ libraryRoot, record }: { libraryRoot: string; record: MoleculeRecord }) =>
      molAdminAdd(libraryRoot, record),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: queryKeys.molecules.all })
    },
  })
}
