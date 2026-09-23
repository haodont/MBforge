/** HTTP client for the Markush review API. */

import { httpPost, invokeWithError } from './_utils'
import { ErrorCode } from '@/utils/errors'

// ============================================================================
// Types — mirror src/mbforge/application/dto/markush.py
// ============================================================================

export type RecognizedRole = 'complete' | 'scaffold' | 'fragment' | 'review_required'
export type ReviewStatus = 'pending' | 'confirmed' | 'rejected' | 'superseded'
export type ReviewAction =
  | 'confirm_complete'
  | 'confirm_scaffold'
  | 'confirm_fragment'
  | 'reject'
  | 'reopen'
  | 'update'
export type RecognitionStatus = 'valid' | 'invalid' | 'low_quality'
export type LabelKindName =
  | 'formula'
  | 'r_group'
  | 'ring'
  | 'compound'
  | 'example'
  | 'unknown'

export interface MarkushEvidenceItem {
  evidence_id: number
  entity_type: string
  entity_id: string
  doc_id: string
  page: number | null
  bbox_x0: number | null
  bbox_y0: number | null
  bbox_x1: number | null
  bbox_y1: number | null
  crop_relpath: string | null
  context_text: string | null
  moldet_confidence: number | null
  scribe_confidence: number | null
  composite_confidence: number | null
}

export interface MarkushDecisionItem {
  decision_id: string
  action: string
  previous_state: string | null
  new_state: string | null
  reason: string
  created_at: string | null
}

export interface MarkushCandidate {
  candidate_id: string
  source_key: string
  doc_id: string
  predicted_role: RecognizedRole
  smiles: string | null
  esmiles: string | null
  name: string
  raw_label: string
  normalized_label: string
  label_kind: LabelKindName
  page: number | null
  bbox_x0: number | null
  bbox_y0: number | null
  bbox_x1: number | null
  bbox_y1: number | null
  crop_relpath: string | null
  moldet_confidence: number | null
  scribe_confidence: number | null
  composite_confidence: number | null
  reasons: string[]
  context_text: string
  properties: Record<string, string> | null
  recognition_status: RecognitionStatus
  review_status: ReviewStatus
  review_version: number
  superseded_at: string | null
  created_at: string | null
  updated_at: string | null
}

export interface MarkushCandidateDetail extends MarkushCandidate {
  scaffold_id: string | null
  fragment_id: string | null
  enumeration_eligible: boolean
  enumeration_block_reasons: string[]
  evidence: MarkushEvidenceItem[] | null
  decisions: MarkushDecisionItem[] | null
}

export interface MarkushListResponse {
  items: MarkushCandidate[]
  total: number
  page: number
  page_size: number
}

export interface MarkushListFilters {
  library_root: string
  doc_id?: string | null
  review_status?: ReviewStatus | null
  predicted_role?: RecognizedRole | null
  reason?: string | null
  page?: number
  page_size?: number
}

export interface MarkushDecisionResponse {
  candidate_id: string
  new_state: ReviewStatus
  new_version: number
  molecule_id: string | null
  scaffold_id: string | null
  fragment_id: string | null
}

export interface MarkushUpdatePayload {
  library_root: string
  entity_id: string
  expected_version: number
  smiles?: string | null
  esmiles?: string | null
  normalized_label?: string | null
  raw_label?: string | null
  predicted_role?: RecognizedRole | null
  note?: string
}

// ============================================================================
// Endpoints
// ============================================================================

/** List the review queue with optional filters. */
export async function markushListCandidates(
  filters: MarkushListFilters,
): Promise<MarkushListResponse> {
  return await invokeWithError(
    () =>
      httpPost<MarkushListResponse>('/api/v1/markush/list', {
        library_root: filters.library_root,
        doc_id: filters.doc_id ?? null,
        review_status: filters.review_status ?? null,
        predicted_role: filters.predicted_role ?? null,
        reason: filters.reason ?? null,
        page: filters.page ?? 1,
        page_size: filters.page_size ?? 50,
      }),
    ErrorCode.MoleculeSearch,
  )
}

/** Fetch one candidate with its evidence chain and decision log. */
export async function markushGetCandidate(
  libraryRoot: string,
  candidateId: string,
): Promise<MarkushCandidateDetail> {
  return await invokeWithError(
    () =>
      httpPost<MarkushCandidateDetail>('/api/v1/markush/get', {
        library_root: libraryRoot,
        candidate_id: candidateId,
      }),
    ErrorCode.MoleculeSearch,
  )
}

/** Apply a confirm / reject / reopen action. */
export async function markushDecide(
  libraryRoot: string,
  entityId: string,
  expectedVersion: number,
  action: ReviewAction,
  reason = '',
): Promise<MarkushDecisionResponse> {
  return await invokeWithError(
    () =>
      httpPost<MarkushDecisionResponse>('/api/v1/markush/decide', {
        library_root: libraryRoot,
        entity_id: entityId,
        expected_version: expectedVersion,
        action,
        reason,
      }),
    ErrorCode.MoleculeSearch,
  )
}

/** Edit SMILES / labels / role of a pending candidate. */
export async function markushUpdateCandidate(
  payload: MarkushUpdatePayload,
): Promise<MarkushCandidateDetail> {
  return await invokeWithError(
    () =>
      httpPost<MarkushCandidateDetail>('/api/v1/markush/update', {
        ...payload,
        note: payload.note ?? '',
      }),
    ErrorCode.MoleculeSearch,
  )
}

// ============================================================================
// Phase 4 — attachment sites / R-group options / mounts
// ============================================================================

export type MountOrigin = 'text_definition' | 'proximity' | 'manual'
export type MountStatus = 'suggested' | 'confirmed' | 'rejected'
export type SiteStatus = 'pending' | 'confirmed' | 'rejected'
export type OptionStatus = 'pending' | 'confirmed' | 'rejected'

export interface MarkushSite {
  site_id: string
  scaffold_id: string
  site_label: string
  atom_map_num: number | null
  attachment_count: number
  bond_type: string | null
  source_text: string
  status: SiteStatus
  properties: Record<string, string>
  created_at: string | null
  updated_at: string | null
  options?: MarkushOption[]
}

export interface MarkushOption {
  option_id: string
  site_id: string
  fragment_id: string | null
  normalized_smiles: string | null
  definition_text: string
  constraints: Record<string, string>
  status: OptionStatus
  created_at: string | null
  updated_at: string | null
}

export interface MarkushMount {
  mount_id: string
  site_id: string
  fragment_id: string
  origin: MountOrigin
  confidence: number | null
  reasons: string[]
  status: MountStatus
  created_at: string | null
  updated_at: string | null
}

export async function markushListSites(
  libraryRoot: string,
  scaffoldId: string,
): Promise<MarkushSite[]> {
  const resp = await invokeWithError(
    () =>
      httpPost<{ items: MarkushSite[] }>('/api/v1/markush/sites/list', {
        library_root: libraryRoot,
        scaffold_id: scaffoldId,
      }),
    ErrorCode.MoleculeSearch,
  )
  return resp.items
}

export async function markushCreateSite(
  libraryRoot: string,
  payload: {
    scaffold_id: string
    site_label: string
    atom_map_num: number | null
    attachment_count?: number
    bond_type?: string | null
    source_text?: string
  },
): Promise<MarkushSite> {
  return await invokeWithError(
    () =>
      httpPost<MarkushSite>('/api/v1/markush/sites/create', {
        library_root: libraryRoot,
        attachment_count: 1,
        source_text: '',
        ...payload,
      }),
    ErrorCode.MoleculeSearch,
  )
}

export async function markushUpdateSite(
  libraryRoot: string,
  payload: {
    site_id: string
    site_label?: string | null
    atom_map_num?: number | null
    attachment_count?: number | null
    bond_type?: string | null
    source_text?: string | null
  },
): Promise<MarkushSite> {
  return await invokeWithError(
    () =>
      httpPost<MarkushSite>('/api/v1/markush/sites/update', {
        library_root: libraryRoot,
        ...payload,
      }),
    ErrorCode.MoleculeSearch,
  )
}

export async function markushListOptions(
  libraryRoot: string,
  siteId: string,
): Promise<MarkushOption[]> {
  const resp = await invokeWithError(
    () =>
      httpPost<{ items: MarkushOption[] }>('/api/v1/markush/options/list', {
        library_root: libraryRoot,
        site_id: siteId,
      }),
    ErrorCode.MoleculeSearch,
  )
  return resp.items
}

export async function markushCreateOption(
  libraryRoot: string,
  payload: {
    site_id: string
    fragment_id?: string | null
    normalized_smiles?: string | null
    definition_text?: string
  },
): Promise<MarkushOption> {
  return await invokeWithError(
    () =>
      httpPost<MarkushOption>('/api/v1/markush/options/create', {
        library_root: libraryRoot,
        constraints: {},
        definition_text: '',
        ...payload,
      }),
    ErrorCode.MoleculeSearch,
  )
}

export async function markushListMounts(
  libraryRoot: string,
  filter: { site_id?: string; scaffold_id?: string; fragment_id?: string } = {},
): Promise<MarkushMount[]> {
  const resp = await invokeWithError(
    () =>
      httpPost<{ items: MarkushMount[] }>('/api/v1/markush/mounts/list', {
        library_root: libraryRoot,
        ...filter,
      }),
    ErrorCode.MoleculeSearch,
  )
  return resp.items
}

export async function markushCreateMount(
  libraryRoot: string,
  payload: {
    site_id: string
    fragment_id: string
    origin?: MountOrigin
    confidence?: number | null
    reasons?: string[]
  },
): Promise<MarkushMount> {
  return await invokeWithError(
    () =>
      httpPost<MarkushMount>('/api/v1/markush/mounts/create', {
        library_root: libraryRoot,
        origin: 'manual',
        reasons: [],
        ...payload,
      }),
    ErrorCode.MoleculeSearch,
  )
}

export async function markushDecideMount(
  libraryRoot: string,
  mountId: string,
  action: 'confirm' | 'reject',
  reason = '',
): Promise<MarkushMount> {
  return await invokeWithError(
    () =>
      httpPost<MarkushMount>('/api/v1/markush/mounts/decide', {
        library_root: libraryRoot,
        mount_id: mountId,
        action,
        reason,
      }),
    ErrorCode.MoleculeSearch,
  )
}

// ============================================================================
// Phase 6: Enumeration
// ============================================================================

export interface SiteSelection {
  site_label: string
  atom_map_num: number
  fragments: string[]
}

export interface EnumerationPreviewResponse {
  theoretical_count: number
  requested_limit: number
  truncated: boolean
}

export interface EnumerationRunResponse {
  run_id: string
  theoretical_count: number
  written_count: number
  truncated: boolean
  status: string
  error: string | null
}

export type GeneratedReviewStatus = 'pending' | 'confirmed' | 'rejected'

export interface GeneratedAssignment {
  site_label: string
  atom_map_num: number
  fragment_id: string
  fragment_smiles: string
}

export interface GeneratedCandidate {
  generated_id: string
  run_id: string
  scaffold_id: string
  combination_key: string
  smiles: string
  canonical_smiles: string
  assignments: GeneratedAssignment[]
  validation_status: string
  review_status: GeneratedReviewStatus
  properties: Record<string, unknown>
  created_at: string
}

export interface GeneratedDecisionResponse {
  generated_id: string
  review_status: GeneratedReviewStatus
  mol_id: string | null
}

export async function markushEnumerationPreview(
  libraryRoot: string,
  scaffoldId: string,
  selection: SiteSelection[],
): Promise<EnumerationPreviewResponse> {
  return await invokeWithError(
    () =>
      httpPost<EnumerationPreviewResponse>('/api/v1/markush/enumeration/preview', {
        library_root: libraryRoot,
        scaffold_id: scaffoldId,
        selection,
      }),
    ErrorCode.MoleculeSearch,
  )
}

export async function markushEnumerationRun(
  libraryRoot: string,
  scaffoldId: string,
  selection: SiteSelection[],
  requestedLimit: number,
): Promise<EnumerationRunResponse> {
  return await invokeWithError(
    () =>
      httpPost<EnumerationRunResponse>('/api/v1/markush/enumeration/run', {
        library_root: libraryRoot,
        scaffold_id: scaffoldId,
        selection,
        requested_limit: requestedLimit,
      }),
    ErrorCode.MoleculeSearch,
  )
}

export async function markushEnumerationResults(
  libraryRoot: string,
  runId: string,
): Promise<GeneratedCandidate[]> {
  const resp = await invokeWithError(
    () =>
      httpPost<{ items: GeneratedCandidate[] }>('/api/v1/markush/enumeration/results', {
        library_root: libraryRoot,
        run_id: runId,
      }),
    ErrorCode.MoleculeSearch,
  )
  return resp.items
}

export async function markushGeneratedDecide(
  libraryRoot: string,
  generatedId: string,
  action: 'confirm' | 'reject',
  reason = '',
): Promise<GeneratedDecisionResponse> {
  return await invokeWithError(
    () =>
      httpPost<GeneratedDecisionResponse>('/api/v1/markush/generated/decide', {
        library_root: libraryRoot,
        entity_id: generatedId,
        action,
        reason,
      }),
    ErrorCode.MoleculeSearch,
  )
}
