/** Detection cache — per-PDF molecule detection via HTTP.
 *
 * - `cachedExtractPage` — cache-aware single-page molecule detection.
 * - `getDetectionCacheStats` — disk usage + page count for Settings.
 * - `clearDetectionCache` — wipe all `index/detections` JSON files.
 */

import { httpPost } from './_utils'
import type { ExtractionResult } from '@/types'

export interface CachedExtractPageResponse {
  results: unknown[]
  count: number
  source: 'cache' | 'sidecar' | 'sidecar_error' | 'cache_miss'
  cache_path?: string | null
  error?: string | null
}

export interface DetectionCacheStats {
  disk_usage_bytes: number
  cached_page_count: number
  cached_doc_count: number
  schema_version: number
}

/** Cache-aware single-page molecule detection.
 *
 * `docId` is the document UUID (`DocumentEntry.doc_id`). The backend resolves
 * the actual PDF source path from the project index.
 */
export async function cachedExtractPage(params: {
  libraryRoot: string
  docId: string
  page: number
  imageBase64: string
  pageWPts: number
  pageHPts: number
  imageW: number
  imageH: number
  force?: boolean
}): Promise<CachedExtractPageResponse> {
  return httpPost<CachedExtractPageResponse>('/api/v1/detection-cache/extract-page', {
    library_root: params.libraryRoot,
    doc_id: params.docId,
    page: params.page,
    image_base64: params.imageBase64,
    page_w_pts: params.pageWPts,
    page_h_pts: params.pageHPts,
    image_w: params.imageW,
    image_h: params.imageH,
    force: params.force ?? false,
  })
}

export async function getDetectionCacheStats(
  libraryRoot: string,
): Promise<DetectionCacheStats> {
  return httpPost<DetectionCacheStats>('/api/v1/detection-cache/stats', { library_root: libraryRoot })
}

export async function clearDetectionCache(libraryRoot: string): Promise<void> {
  await httpPost('/api/v1/detection-cache/clear', { library_root: libraryRoot })
}

export async function clearDetectionCacheForDoc(
  libraryRoot: string,
  docId: string,
): Promise<void> {
  await httpPost('/api/v1/detection-cache/clear-doc', { library_root: libraryRoot, doc_id: docId })
}

// ---------------------------------------------------------------------------
// 实时 MoldDet 检测（不读缓存，每次调用都跑检测器 + MolParser）
// ---------------------------------------------------------------------------

function normalizeDetection(raw: Record<string, unknown>, page: number, index: number): ExtractionResult {
  const rawBbox = raw.bbox_pdf ?? raw.bbox
  const bbox = Array.isArray(rawBbox)
    ? rawBbox.map(Number) as [number, number, number, number]
    : rawBbox && typeof rawBbox === 'object'
      ? [
        Number((rawBbox as Record<string, unknown>).x1),
        Number((rawBbox as Record<string, unknown>).y1),
        Number((rawBbox as Record<string, unknown>).x2),
        Number((rawBbox as Record<string, unknown>).y2),
      ] as [number, number, number, number]
      : null
  const confidence = Number(raw.moldet_conf ?? raw.confidence ?? 0)
  const esmiles = typeof raw.esmiles === 'string'
    ? raw.esmiles
    : typeof raw.smiles === 'string' ? raw.smiles : ''
  // MolParser 后端同时返回 Layer1 smiles（纯 SMILES）与 Layer2 esmiles（可能含
  // <sep> 标签）；RDKit 渲染必须用 smiles，故优先取 raw.smiles。
  const smiles = typeof raw.smiles === 'string' && raw.smiles
    ? raw.smiles
    : esmiles
  const name = typeof raw.name === 'string'
    ? raw.name
    : `Mol_${String(index + 1).padStart(3, '0')}`
  const contextText = typeof raw.context_text === 'string' ? raw.context_text : ''

  return {
    evidence_id: typeof raw.evidence_id === 'string' ? raw.evidence_id : undefined,
    esmiles,
    smiles,
    name,
    source: 'image',
    moldet_conf: confidence,
    bbox_pdf: bbox,
    page_idx: Number.isFinite(Number(raw.page_idx)) ? Number(raw.page_idx) : page - 1,
    context_text: contextText,
    mol_img_path: typeof raw.mol_img_path === 'string' ? raw.mol_img_path : null,
    status: 'pending',
    properties: raw.properties && typeof raw.properties === 'object'
      ? raw.properties as Record<string, unknown>
      : {},
  }
}

/** Run MoldDet + MolParser on a single PDF page (no cache read). */
export async function extractPdfMolecules(params: {
  libraryRoot: string
  docId: string
  page: number
}): Promise<ExtractionResult[]> {
  const resp = await httpPost<{
    molecules: unknown[]
    count: number
    page_num: number
    width: number
    height: number
  }>('/api/v1/moldet/extract-pdf', {
    library_root: params.libraryRoot,
    doc_id: params.docId,
    page: params.page,
    dpi: 300,
  })
  return resp.molecules.map((raw, index) =>
    normalizeDetection(raw as Record<string, unknown>, params.page, index))
}

/** Persist detection results so later PDF opens can use the cache. */
export async function savePageDetections(
  libraryRoot: string,
  docId: string,
  page: number,
  results: ExtractionResult[],
): Promise<void> {
  await httpPost('/api/v1/detection-cache/save', {
    library_root: libraryRoot,
    detections: results.map((result, index) => ({
      mol_id: result.name || `Mol_${String(index + 1).padStart(3, '0')}`,
      doc_id: docId,
      page,
      bbox_x0: result.bbox_pdf?.[0] ?? null,
      bbox_y0: result.bbox_pdf?.[1] ?? null,
      bbox_x1: result.bbox_pdf?.[2] ?? null,
      bbox_y1: result.bbox_pdf?.[3] ?? null,
      conf_moldet: result.moldet_conf,
      vlm_verified_esmiles: result.esmiles,
    })),
  })
}

// ---------------------------------------------------------------------------
// 批量快速 MoldDet 扫描
// ---------------------------------------------------------------------------

export interface QuickMoldetPageResult {
  page: number
  has_molecule: boolean
  bbox_count: number
}

export interface QuickMoldetDocResult {
  path: string
  doc_slug: string
  doc_id: string
  page_count: number
  pages: QuickMoldetPageResult[]
  pages_with_molecules: number[]
  moldet_status: string
  error?: string | null
}

export interface BatchQuickMoldetResponse {
  results: QuickMoldetDocResult[]
  processed: number
  total: number
  errors: string[]
}

/** 批量快速 MoldDet 扫描：只检测 bbox，不识别 SMILES。 */
export async function batchQuickMoldetScan(
  libraryRoot: string,
  docIds?: string[],
): Promise<BatchQuickMoldetResponse> {
  return httpPost<BatchQuickMoldetResponse>('/api/v1/detection-cache/batch-scan', {
    library_root: libraryRoot,
    doc_ids: docIds ?? [],
  })
}
