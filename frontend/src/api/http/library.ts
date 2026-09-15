/** Library API — unified document library. */

import { apiUrl, httpGet, httpGetText, httpPost, httpFetch, invokeWithError } from './_utils'

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
  coref: string
  kind: string
}

export interface PatentFactsSection {
  section_id: string
  title: string
  kind: string
  page_start: number
  page_end: number
  evidence_ids: string[]
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

export interface PatentFactsArtifact {
  doc_id: string
  run_id: string
  sections: PatentFactsSection[]
  entries: PatentFactsEntry[]
  synthesis_steps: Record<string, unknown>[]
  assay_methods: PatentFactsAssayMethod[]
  examples: PatentFactsExample[]
  measurements: PatentFactsMeasurement[]
  issues: Record<string, unknown>[]
  stats: Record<string, unknown>
}

export interface CollectionInfo {
  collection_id: string
  name: string
  parent_id: string | null
  doc_count: number
}

export interface CollectionNode extends CollectionInfo {
  children: CollectionNode[]
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
    ? await new Promise<{ success: boolean; document?: DocumentInfo; run_id?: string; error?: string; detail?: string }>((resolve, reject) => {
        const request = new XMLHttpRequest()
        request.open('POST', apiUrl('/library/import'))
        request.upload.onprogress = (event) => {
          if (event.lengthComputable) onProgress(Math.round((event.loaded / event.total) * 100))
        }
        request.onload = () => {
          let body: { success: boolean; document?: DocumentInfo; run_id?: string; error?: string; detail?: string } | null
          try {
            body = JSON.parse(request.responseText) as { success: boolean; document?: DocumentInfo; run_id?: string; error?: string; detail?: string }
          } catch {
            body = null
          }
          if (request.status >= 400) {
            reject(new Error(body?.error ?? body?.detail ?? `Import failed (HTTP ${request.status})`))
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

export async function listDocuments(
  collectionId?: string
): Promise<{ documents: DocumentInfo[] }> {
  return invokeWithError(() =>
    httpPost('/api/v1/library/documents', { collection_id: collectionId })
  )
}

export async function deleteDocument(
  docId: string
): Promise<{ success: boolean }> {
  return invokeWithError(() =>
    httpPost('/api/v1/library/documents/delete', { doc_id: docId })
  )
}

/** Clear a document's pipeline outputs (restore pre-pipeline state). */
export async function clearDocument(
  docId: string
): Promise<{ success: boolean }> {
  return invokeWithError(() =>
    httpPost('/api/v1/library/documents/clear', { doc_id: docId })
  )
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

// ── Collections ─────────────────────────────────────

export async function createCollection(
  name: string,
  parentId?: string
): Promise<{ success: boolean; collection?: CollectionInfo; error?: string }> {
  return invokeWithError(() =>
    httpPost('/api/v1/library/collections/create', { name, parent_id: parentId })
  )
}

export async function renameCollection(
  collectionId: string,
  name: string
): Promise<{ success: boolean }> {
  return invokeWithError(() =>
    httpPost('/api/v1/library/collections/rename', {
      collection_id: collectionId,
      name,
    })
  )
}

export async function listCollections(): Promise<{ collections: CollectionNode[] }> {
  return invokeWithError(() =>
    httpPost('/api/v1/library/collections/list', {})
  )
}

export async function deleteCollection(
  collectionId: string
): Promise<{ success: boolean }> {
  return invokeWithError(() =>
    httpPost('/api/v1/library/collections/delete', { collection_id: collectionId })
  )
}

export async function addDocumentToCollection(
  collectionId: string,
  docId: string
): Promise<{ success: boolean }> {
  return invokeWithError(() =>
    httpPost('/api/v1/library/collections/add-document', {
      collection_id: collectionId,
      doc_id: docId,
    })
  )
}

export async function removeDocumentFromCollection(
  collectionId: string,
  docId: string
): Promise<{ success: boolean }> {
  return invokeWithError(() =>
    httpPost('/api/v1/library/collections/remove-document', {
      collection_id: collectionId,
      doc_id: docId,
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

export function imageUrl(docId: string, filename: string, libraryRoot: string): string {
  return artifactUrl(
    `/documents/${encodeURIComponent(docId)}/images/${encodeURIComponent(filename)}`,
    libraryRoot
  )
}

export async function fetchPageText(
  docId: string,
  page: number,
  libraryRoot: string
): Promise<{ ok: true; text: string } | { ok: false; error: string }> {
  try {
    const text = await httpGetText(artifactUrl(`/documents/${encodeURIComponent(docId)}/pages/${page}`, libraryRoot))
    return { ok: true, text }
  } catch (e) {
    return { ok: false, error: e instanceof Error ? e.message : String(e) }
  }
}
