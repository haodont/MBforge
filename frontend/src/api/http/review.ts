/** HTTP client for the unified human-review queue. */

import { httpGet, httpPost, invokeWithError } from './_utils'
import { ErrorCode } from '@/utils/errors'

export type ReviewKind =
  | 'low_conf_molecule'
  | 'review_required'
  | 'unparsable_smiles'
  | 'activity_match'
  | 'missing_evidence'
  | 'ambiguous_coref'
  | 'markush_link'
export type ReviewStatus = 'pending' | 'confirmed' | 'rejected'
export type ReviewAction = 'confirm' | 'reject' | 'reopen'

export type ReviewBbox = [number | null, number | null, number | null, number | null]

/** Payload keyed by review kind — add/refine per kind as backend fields stabilize. */
export type ReviewPayload =
  | { kind: 'low_conf_molecule'; mol_id?: string; evidence?: unknown }
  | { kind: 'review_required'; reason?: string }
  | { kind: 'unparsable_smiles'; smiles?: string }
  | { kind: 'activity_match'; activity?: unknown }
  | { kind: 'missing_evidence'; notes?: string }
  | { kind: 'ambiguous_coref'; mol_id?: string; ocr_labels?: string[]; coref_primary?: string }
  | { kind: 'markush_link'; markush?: unknown }

export interface ReviewQueueItem {
  id: string
  kind: ReviewKind
  doc_id: string | null
  page: number | null
  bbox: ReviewBbox | null
  crop_relpath: string | null
  smiles: string | null
  name: string | null
  confidence: number | null
  reasons: string[]
  context_text: string | null
  status: ReviewStatus
  payload: Record<string, unknown> & Partial<ReviewPayload>
  created_at: string | null
  resolved_at: string | null
}

export interface ReviewQueueResponse {
  items: ReviewQueueItem[]
  total: number
  page: number
  page_size: number
}

export interface ReviewStatsResponse {
  items: Array<{ kind: ReviewKind; status: ReviewStatus; count: number }>
  pending: number
}

export interface ReviewHistoryEntry {
  kind: ReviewKind
  status: ReviewStatus
  action: ReviewAction
  reason?: string | null
  created_at?: string | null
  [key: string]: unknown
}

export interface ReviewHistoryResponse {
  entity_type: string
  entity_id: string
  history: ReviewHistoryEntry[]
}

export interface ReviewDecisionResult {
  id: string
  kind: ReviewKind
  status?: ReviewStatus
  error?: string
  [key: string]: unknown
}

export interface ReviewDecisionResponse {
  updated: number
  skipped: number
  results: ReviewDecisionResult[]
}

export interface ReviewClearResponse {
  deleted_items: number
  deleted_candidates: number
}

function query(params: Record<string, string | number | undefined>): string {
  const values = Object.entries(params)
    .filter(([, value]) => value !== undefined && value !== '')
    .map(([key, value]) => `${encodeURIComponent(key)}=${encodeURIComponent(String(value))}`)
  return values.length ? `?${values.join('&')}` : ''
}

export async function reviewQueue(
  libraryRoot: string,
  filters: { kind?: ReviewKind; status?: ReviewStatus; docId?: string; page?: number; pageSize?: number } = {},
): Promise<ReviewQueueResponse> {
  return await invokeWithError(
    () => httpGet<ReviewQueueResponse>(`/api/v1/review/queue${query({
      library_root: libraryRoot,
      kind: filters.kind,
      status: filters.status,
      doc_id: filters.docId,
      page: filters.page ?? 1,
      page_size: filters.pageSize ?? 50,
    })}`),
    ErrorCode.MoleculeSearch,
  )
}

export async function reviewStats(libraryRoot: string): Promise<ReviewStatsResponse> {
  return await invokeWithError(
    () => httpGet<ReviewStatsResponse>(`/api/v1/review/stats${query({ library_root: libraryRoot })}`),
    ErrorCode.MoleculeSearch,
  )
}

export async function reviewItem(libraryRoot: string, kind: ReviewKind, id: string): Promise<ReviewQueueItem> {
  return await invokeWithError(
    () => httpGet<ReviewQueueItem>(`/api/v1/review/items/${encodeURIComponent(kind)}/${encodeURIComponent(id)}${query({ library_root: libraryRoot })}`),
    ErrorCode.MoleculeSearch,
  )
}

export async function reviewHistory(libraryRoot: string, entityId: string): Promise<ReviewHistoryResponse> {
  return await invokeWithError(
    () => httpGet<ReviewHistoryResponse>(`/api/v1/review/history${query({ library_root: libraryRoot, entity_id: entityId })}`),
    ErrorCode.MoleculeSearch,
  )
}

export async function reviewDecide(
  libraryRoot: string,
  items: Array<{ kind: ReviewKind; id: string; choice?: string | null }>,
  action: ReviewAction,
  reason = '',
): Promise<ReviewDecisionResponse> {
  return await invokeWithError(
    () => httpPost<ReviewDecisionResponse>('/api/v1/review/decide', {
      library_root: libraryRoot,
      items,
      action,
      reason,
    }),
    ErrorCode.MoleculeSearch,
  )
}

export async function reviewClear(libraryRoot: string): Promise<ReviewClearResponse> {
  return await invokeWithError(
    () => httpPost<ReviewClearResponse>('/api/v1/review/clear', {
      library_root: libraryRoot,
    }),
    ErrorCode.MoleculeSearch,
  )
}
