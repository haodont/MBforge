/** Library API — unified document library. */

import { apiUrl, httpGet, httpGetText, httpPost, httpPostBlob, httpFetch, invokeWithError } from './_utils'
import { AppError, ErrorCode } from '@/utils/errors'

// ── Types ───────────────────────────────────────────

export interface DocumentInfo {
  doc_id: string
  title: string
  file_name: string
  page_count: number
  status: string
  created_at: string
}

export interface DocumentEvidenceItem {
  evidence_id: string
  doc_id: string
  page: number
  bbox: [number, number, number, number]
  raw_text: string
  kind: string
  category: string
  /**
   * Paragraph this row belongs to (empty when the row is not in one), the
   * patent's own paragraph number (null when unnumbered), and whether this row
   * contributed the paragraph's first fragment. A paragraph split across a page
   * break shares one paragraph_id; its later rows carry paragraph_start=false.
   */
  paragraph_id: string
  paragraph_number: string | null
  paragraph_start: boolean
  /** Line index inside the paragraph, and that line's left-edge depth. */
  paragraph_line: number
  indent_level: number
}

export interface PatentFactsSection {
  section_id: string
  title: string
  kind: string
  page_start: number
  page_end: number
  evidence_ids: string[]
}

export interface PatentFactsName {
  name_id: string
  label_key: string
  label_raw: string
  name_raw: string
  name_clean: string
  page: number | null
  evidence_ids: string[]
  attribution: 'resolved' | 'unresolved'
}

export interface PatentFactsCharacterization {
  characterization_id: string
  technique: 'nmr' | 'ms' | 'elemental'
  raw_text: string
  label_key: string
  page: number | null
  evidence_ids: string[]
  attribution: 'resolved' | 'unresolved'
}

export interface PatentFactsSynthesisStep {
  step_no: number
  text: string
  evidence_ids: string[]
}

export interface PatentFactsSynthesisRoute {
  route_id: string
  section_id: string
  kind: string
  title: string
  label_raw: string
  label_key: string
  product_label: string
  page_start: number | null
  page_end: number | null
  evidence_ids: string[]
  steps: PatentFactsSynthesisStep[]
  step_count: number
  yield_raw: string
  method_note: string
  attribution: 'resolved' | 'unresolved'
}

export interface PatentFactsEntry {
  entry_id: string
  label_raw: string
  label_key: string
  entry_role: string
  name_raw: string
  section_id: string
  entity_id: string | null
  structure_status: string
  extraction_status: string
  linking_status: string
  review_status: string
  evidence_ids: string[]
}

export interface PatentFactsMeasurement {
  measurement_id: string
  doc_id: string
  compound_entry_id: string | null
  assay_method_id: string | null
  mol_id: string | null
  metric: string | null
  linking_status: string
  value: {
    raw_text: string
    operator: string
    original_value: number | null
    original_unit: string
    canonical_value: number | null
    canonical_unit: string
    qualitative_value: string
  }
  evidence_ids: string[]
  provenance: Record<string, unknown>
}

export interface PatentFactsAssayMethod {
  assay_method_id: string
  doc_id: string
  target: string | null
  system: string | null
  endpoint: string | null
  assay_type: string | null
  conditions: Record<string, unknown>
  raw_text: string
  section_id: string
  page_start: number
  page_end: number
  evidence_ids: string[]
}

export interface PatentFactsExample {
  example_idx: number
  page_num: number
  heading: string
  labels: string[]
  evidence_ids: string[]
}

export interface PatentConflictCandidate {
  source: 'deterministic' | 'llm'
  fields: Record<string, unknown> & { value_text?: string }
  signature: string
  evidence_ids: string[]
}

export interface PatentConflict {
  conflict_id: string
  slot_id: string
  kind: 'measurement' | 'assay_method'
  doc_id: string
  page: number | null
  evidence_ids: string[]
  candidates: PatentConflictCandidate[]
}

export interface PatentReviewCandidate {
  review_item_id: string
  reason: string
  kind: string
  page: number | null
  evidence_ids: string[]
  deterministic: Array<Record<string, unknown> & { value_text?: string; raw_text?: string }> | null
  llm: (Record<string, unknown> & { value_text?: string; raw_text?: string })
    | Array<Record<string, unknown> & { value_text?: string; raw_text?: string }>
    | null
  conflict: PatentConflict | null
}

export interface PatentFactsIssue {
  code?: string
  message?: string
  severity?: string
  evidence_ids?: string[]
  related_fact_id?: string | null
}

export interface PatentFactsArtifact {
  doc_id: string
  run_id: string
  revision?: number
  projection_status?: 'current' | 'pending' | 'legacy' | null
  coverage?: {
    total_evidence: number
    complete_evidence: number
    partial_evidence: number
    complete_pages: number[]
    partial_pages: number[]
    unread_pages: number[]
    no_evidence_pages: number[]
  } | null
  sections: PatentFactsSection[]
  entries: PatentFactsEntry[]
  /** Printed chemistry names for a designation (verbsatim, never derived). */
  names?: PatentFactsName[]
  /** Printed spectra / elemental lines, verbatim, with their owner. */
  characterizations?: PatentFactsCharacterization[]
  /** Preparation routes: verbatim steps, the printed yield, the section's pages. */
  synthesis_steps: PatentFactsSynthesisRoute[]
  assay_methods: PatentFactsAssayMethod[]
  examples: PatentFactsExample[]
  measurements: PatentFactsMeasurement[]
  issues: PatentFactsIssue[]
  stats: Record<string, unknown>
  analysis_status?: 'disabled' | 'succeeded' | 'fallback'
  extraction_mode?: 'deterministic' | 'hybrid'
  conflicts?: PatentConflict[]
  review_candidates?: PatentReviewCandidate[]
  llm?: {
    error_code?: string
    error?: string
    turns?: number
    tool_calls?: number
    tokens?: number | null
    duration_ms?: number
    model?: string
    prompt_version?: string
  }
}

export interface LibraryStatus {
  configured: boolean
  root: string
  doc_count: number
}

// ── Status ──────────────────────────────────────────

export async function getLibraryStatus(): Promise<LibraryStatus> {
  return invokeWithError(() => httpGet<LibraryStatus>('/api/v1/library/status'))
}

// ── Documents ───────────────────────────────────────

export async function importDocument(
  file: File,
  title?: string,
  onProgress?: (percent: number) => void,
): Promise<{ success: boolean; document?: DocumentInfo; run_id?: string }> {
  const fd = new FormData()
  fd.append('file', file, file.name)
  if (title) fd.append('title', title)

  const resp = onProgress && typeof XMLHttpRequest !== 'undefined'
    ? await new Promise<{ success: boolean; document?: DocumentInfo; run_id?: string; error?: string; detail?: string; error_code?: string }>((resolve, reject) => {
        const request = new XMLHttpRequest()
        request.open('POST', apiUrl('/library/import'))
        request.upload.onprogress = (event) => {
          if (event.lengthComputable) onProgress(Math.round((event.loaded / event.total) * 100))
        }
        request.onload = () => {
          let body: { success: boolean; document?: DocumentInfo; run_id?: string; error?: string; detail?: string; error_code?: string } | null
          try {
            body = JSON.parse(request.responseText) as { success: boolean; document?: DocumentInfo; run_id?: string; error?: string; detail?: string; error_code?: string }
          } catch {
            body = null
          }
          if (request.status >= 400) {
            const message = body?.error ?? body?.detail ?? `Import failed (HTTP ${request.status})`
            reject(body?.error_code === 'duplicate_filename'
              ? new AppError(ErrorCode.ApiError, message, { context: { backend_code: body.error_code } })
              : new Error(message))
            return
          }
          if (body === null) {
            reject(new Error('Invalid import response'))
            return
          }
          resolve(body)
        }
        request.onerror = () => reject(new Error('Import request failed'))
        request.send(fd)
      })
    : await httpFetch<{ success: boolean; document?: DocumentInfo; run_id?: string; error?: string; detail?: string }>(
        '/library/import', { method: 'POST', body: fd },
      )

  if (!resp.success) throw new Error(resp.error || resp.detail || 'Import failed')
  onProgress?.(100)
  return resp
}

export async function listDocuments(): Promise<{ documents: DocumentInfo[] }> {
  return invokeWithError(() =>
    httpPost('/api/v1/library/documents', {})
  )
}

export async function deleteDocuments(
  docIds: string[]
): Promise<{ success: boolean; deleted: number }> {
  return invokeWithError(() =>
    httpPost('/api/v1/library/documents/delete', { doc_ids: docIds })
  )
}

export interface PatentAnalysisResult {
  success: boolean
  enqueued: number
  skipped: number
}

/** Queue a Patent-only analysis run for each eligible document (batch). */
export async function runPatentAnalysis(docIds: string[]): Promise<PatentAnalysisResult> {
  return invokeWithError(() =>
    httpPost('/api/v1/documents/patent-analysis', { doc_ids: docIds })
  )
}

/** Download all readings and their source evidence for the selected documents. */
export async function exportStructureActivity(docIds: string[], libraryRoot: string): Promise<void> {
  const blob = await httpPostBlob('/api/v1/activities/export', {
    doc_ids: docIds,
    library_root: libraryRoot,
  })
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = 'structure-activity.zip'
  document.body.appendChild(anchor)
  try {
    anchor.click()
  } finally {
    anchor.remove()
    window.setTimeout(() => URL.revokeObjectURL(url), 0)
  }
}

export async function updateMoleculeEvidence(
  docId: string,
  evidenceId: string,
  name: string,
  smiles: string,
): Promise<{ success: boolean; evidence_id: string }> {
  return invokeWithError(() =>
    httpPost(`/api/v1/library/documents/${encodeURIComponent(docId)}/evidence/${encodeURIComponent(evidenceId)}/molecule`, {
      name,
      smiles,
    })
  )
}

// ── Configuration ───────────────────────────────────

export async function configureLibrary(
  root: string
): Promise<{ success: boolean; root?: string; error?: string }> {
  return invokeWithError(() =>
    httpPost('/api/v1/library/configure', { root })
  )
}

// ── Pipeline artifacts (used by DocumentViewer) ───────────

function artifactUrl(path: string, libraryRoot: string, extraParams?: Record<string, string>): string {
  const params = new URLSearchParams({ library_root: libraryRoot })
  if (extraParams) {
    for (const [k, v] of Object.entries(extraParams)) {
      params.set(k, v)
    }
  }
  return apiUrl(`/api/v1/library${path}?${params.toString()}`)
}

export async function fetchDocumentMarkdown(
  docId: string,
  libraryRoot: string
): Promise<{ ok: true; text: string } | { ok: false; error: string }> {
  try {
    const text = await httpGetText(artifactUrl(`/documents/${encodeURIComponent(docId)}/markdown`, libraryRoot))
    return { ok: true, text }
  } catch (e) {
    return { ok: false, error: e instanceof Error ? e.message : String(e) }
  }
}

export async function fetchReportJson(
  docId: string,
  libraryRoot: string
): Promise<{ ok: true; data: unknown } | { ok: false; error: string }> {
  try {
    const data = await httpGet<unknown>(artifactUrl(`/documents/${encodeURIComponent(docId)}/report`, libraryRoot))
    return { ok: true, data }
  } catch (e) {
    return { ok: false, error: e instanceof Error ? e.message : String(e) }
  }
}

export async function fetchPatentFacts(
  docId: string,
  libraryRoot: string
): Promise<{ ok: true; data: PatentFactsArtifact } | { ok: false; error: string }> {
  try {
    const data = await httpGet<PatentFactsArtifact>(artifactUrl(`/documents/${encodeURIComponent(docId)}/patent-facts`, libraryRoot))
    return { ok: true, data }
  } catch (e) {
    return { ok: false, error: e instanceof Error ? e.message : String(e) }
  }
}

export async function fetchDocumentEvidence(
  docId: string,
  page: number,
  libraryRoot: string
): Promise<{ ok: true; data: DocumentEvidenceItem[] } | { ok: false; error: string }> {
  try {
    const data = await httpGet<DocumentEvidenceItem[]>(
      artifactUrl(
        `/documents/${encodeURIComponent(docId)}/evidence`,
        libraryRoot,
        { page: String(page) },
      )
    )
    return { ok: true, data }
  } catch (e) {
    return { ok: false, error: e instanceof Error ? e.message : String(e) }
  }
}

export function cropImageUrl(docId: string, relPath: string, libraryRoot: string): string {
  return artifactUrl(
    `/documents/${encodeURIComponent(docId)}/crop`,
    libraryRoot,
    { rel_path: relPath }
  )
}

export async function resolveDocumentEvidence(docId: string, evidenceId: string, libraryRoot: string): Promise<DocumentEvidenceItem> {
  return httpGet<DocumentEvidenceItem>(artifactUrl(`/documents/${encodeURIComponent(docId)}/evidence/${encodeURIComponent(evidenceId)}`, libraryRoot))
}

/**
 * Resolve many evidence ids in one request (bounded at 50 by the backend).
 *
 * A per-compound view links several passages, and resolving them one by one would
 * issue one request per passage; unknown or foreign ids simply come back missing.
 */
export async function resolveDocumentEvidenceBatch(
  docId: string,
  evidenceIds: string[],
  libraryRoot: string,
): Promise<DocumentEvidenceItem[]> {
  if (evidenceIds.length === 0) return []
  return httpPost<DocumentEvidenceItem[]>(
    artifactUrl(`/documents/${encodeURIComponent(docId)}/evidence/resolve`, libraryRoot),
    { evidence_ids: evidenceIds.slice(0, 50) },
  )
}