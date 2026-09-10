/** Chem / SAR / relation / cluster analysis wrappers (client.ts compatible). */

import { httpPost, invokeWithError } from './_utils'
import { ErrorCode } from '@/utils/errors'

export interface MoleculeStats {
  total: number
  with_activity?: number
  pending?: number
}

// ============================================================================
// 化学信息学 (FastAPI 后端,通过 /api/v1/chem/* 路由访问 Python 侧 RDKit/chematic)
// ============================================================================


export interface SmilesValidation {
  valid: boolean
  canonical_smiles: string | null
  error: string | null
}

async function requestSmilesValidation(smiles: string): Promise<SmilesValidation> {
  const responses = await invokeWithError(
    () => httpPost<SmilesValidation[]>('/api/v1/chem/validate-smiles', { smiles }),
    ErrorCode.ApiError,
  )
  if (responses.length !== 1) {
    throw new Error('SMILES validation returned an unexpected result count')
  }
  return responses[0]
}

export async function chemValidateSmiles(smiles: string): Promise<SmilesValidation> {
  return requestSmilesValidation(smiles)
}

export interface ValidationIssue {
  code: string
  message: string
  severity: 'error' | 'warning'
}

export interface ValidateResponse {
  valid: boolean
  canonical_smiles: string | null
  issues: ValidationIssue[]
}

export async function validateSmiles(smiles: string): Promise<ValidateResponse> {
  const raw = await requestSmilesValidation(smiles)
  if (raw.valid) {
    return { valid: true, canonical_smiles: raw.canonical_smiles, issues: [] }
  }
  const message = raw.error ?? 'SMILES 解析失败'
  return {
    valid: false,
    canonical_smiles: raw.canonical_smiles,
    issues: [{ code: 'SYNTAX', severity: 'error', message }],
  }
}

export async function chemTanimotoSimilarity(smilesA: string, smilesB: string): Promise<number> {
  const resp = await invokeWithError(
    () => httpPost<{ similarity: number }>('/api/v1/chem/tanimoto', { smiles_a: smilesA, smiles_b: smilesB }),
    ErrorCode.ApiError,
  )
  return resp.similarity
}

export async function chemTanimotoBatchFilter(
  querySmiles: string,
  candidates: Array<[string, string]>,
  threshold = 0.5,
): Promise<Array<[string, string, number]>> {
  return invokeWithError(
    () => httpPost<Array<[string, string, number]>>('/api/v1/chem/substructure-search', {
      query: querySmiles,
      candidates,
      threshold,
    }),
    ErrorCode.ApiError,
  )
}

// ============================================================================
// 化学描述符
// ============================================================================

// Chem endpoints (here: /chem/properties) return `{success, result}` envelopes;
// unwrap locally so callers receive the bare value.
// See frontend/src/api/http/chem.ts for the shared convention.
type ChemEnvelope = { success: boolean; error?: string } & Record<string, unknown>
function unwrapChem<T>(raw: unknown, extract: (e: ChemEnvelope) => T): T {
  const env = raw as Record<string, unknown> | null
  if (env && typeof env === 'object' && env.success === true) {
    return extract(env as ChemEnvelope)
  }
  if (env && typeof env === 'object' && env.success === false) {
    throw new Error(typeof env.error === 'string' ? env.error : 'chem request failed')
  }
  return raw as T
}

export interface ChemDescriptors {
  molecular_weight: number
  logp: number
  tpsa: number
  hba: number
  hbd: number
  rotatable_bonds: number
  formula: string
}

export async function chemDescriptors(smiles: string): Promise<ChemDescriptors> {
  const raw = await invokeWithError(
    () => httpPost<unknown>('/api/v1/chem/properties', { smiles }),
    ErrorCode.ApiError,
  )
  return unwrapChem(raw, e => e.properties as ChemDescriptors)
}

/** Render SMILES locally with RDKit; supports Markush wildcard atoms such as `*`. */
export async function smilesToRdkitSvg(
  smiles: string,
  width = 360,
  height = 240,
): Promise<string> {
  const raw = await invokeWithError(
    () => httpPost<unknown>('/api/v1/chem/smiles-to-image', { smiles, width, height }),
    ErrorCode.ApiError,
  )
  return unwrapChem(raw, e => e.svg as string)
}

// ============================================================================
// SAR 分析
// ============================================================================

export interface ScaffoldActivityRecord {
  mol_id: string
  esmiles: string
  name: string
  activity: number | null
  activity_type: string
  units: string
}

export interface ActivitySummary {
  count_with_activity: number
  count_without_activity: number
  min_activity: number | null
  max_activity: number | null
  mean_activity: number | null
}

export interface ScaffoldProfile {
  scaffold_esmiles: string
  molecule_count: number
  activities: ScaffoldActivityRecord[]
  activity_summary: ActivitySummary
}

export async function molScaffoldProfile(
  libraryRoot: string,
  scaffoldEsmiles: string,
): Promise<ScaffoldProfile> {
  return invokeWithError(
    () => httpPost<ScaffoldProfile>('/api/v1/molecule/search', {
      library_root: libraryRoot,
      query: scaffoldEsmiles,
    }),
    ErrorCode.ApiError,
  )
}

export interface ActivityCliff {
  mol_a_id: string
  mol_b_id: string
  mol_a_esmiles: string
  mol_b_esmiles: string
  mol_a_name: string
  mol_b_name: string
  similarity_score: number
  activity_a: number | null
  activity_b: number | null
  activity_ratio: number | null
  activity_type: string
}

export async function molFindActivityCliffs(
  libraryRoot: string,
  minSimilarity: number,
  minActivityRatio: number,
): Promise<ActivityCliff[]> {
  return invokeWithError(
    () => httpPost<ActivityCliff[]>('/api/v1/molecule/search', {
      library_root: libraryRoot,
      min_similarity: minSimilarity,
      min_activity_ratio: minActivityRatio,
    }),
    ErrorCode.ApiError,
  )
}

// ============================================================================
// 分子关系 / 聚类 / 高级分析
// ============================================================================

export interface MoleculeRelation {
  id?: number
  mol_a_id: string
  mol_b_id: string
  relation_type: 'similar' | 'same_as' | 'scaffold' | 'cluster'
  score: number | null
  metadata: Record<string, unknown> | null
  created_at: string
  [key: string]: unknown
}

export interface RelationStats {
  total: number
  similar: number
  same_as: number
  scaffold: number
  cluster: number
}

export interface ClusterInfo {
  cluster_id: string
  member_count: number
  members: string[]
  metadata: Record<string, unknown>
  [key: string]: unknown
}

export interface DedupPair {
  mol_a_id: string
  mol_b_id: string
  confidence: number
  reason: string
  [key: string]: unknown
}

export interface DedupResult {
  duplicates: DedupPair[]
  new_mols: string[]
  relations_added: number
}

export interface AnalogWithActivity {
  mol_id: string
  esmiles: string
  name: string
  similarity_score: number
  activity: number | null
  activity_type: string
  units: string
  [key: string]: unknown
}

export interface SubstructureMatch {
  mol_id: string
  esmiles: string
  [key: string]: unknown
}

// ---- 关系管理 (no HTTP route — kept for API compat) ----

export function molAddRelation(
  _molAId: string,
  _molBId: string,
  _relationType: string,
  _score?: number,
  _metadata?: Record<string, unknown>,
): Promise<number> {
  throw new Error('molAddRelation: no HTTP route available yet')
}

export function molDeleteRelation(_id: number): Promise<boolean> {
  throw new Error('molDeleteRelation: no HTTP route available yet')
}

export function molGetRelation(_id: number): Promise<MoleculeRelation | null> {
  throw new Error('molGetRelation: no HTTP route available yet')
}

export function molFindByMolecule(_molId: string): Promise<MoleculeRelation[]> {
  throw new Error('molFindByMolecule: no HTTP route available yet')
}

export function molFindSimilar(
  _molId: string,
  _minScore: number,
): Promise<Array<{ relation: MoleculeRelation; score: number }>> {
  throw new Error('molFindSimilar: no HTTP route available yet')
}

export function molFindSameAs(_molId: string): Promise<MoleculeRelation[]> {
  throw new Error('molFindSameAs: no HTTP route available yet')
}

export function molGetStats(): Promise<RelationStats> {
  throw new Error('molGetStats: no HTTP route available yet')
}

// ---- 聚类管理 ----

export function molAssignCluster(_molId: string, _clusterId: string): Promise<number> {
  throw new Error('molAssignCluster: no HTTP route available yet')
}

export function molRemoveFromCluster(_molId: string, _clusterId: string): Promise<boolean> {
  throw new Error('molRemoveFromCluster: no HTTP route available yet')
}

export function molGetClusterMembers(_clusterId: string): Promise<ClusterInfo> {
  throw new Error('molGetClusterMembers: no HTTP route available yet')
}

export function molGetMoleculeClusters(_molId: string): Promise<string[]> {
  throw new Error('molGetMoleculeClusters: no HTTP route available yet')
}

export function molListClusters(): Promise<ClusterInfo[]> {
  throw new Error('molListClusters: no HTTP route available yet')
}

// ---- 高级分析 ----

export function molFindAnalogsWithActivity(
  _molId: string,
  _minSimilarity: number,
): Promise<AnalogWithActivity[]> {
  throw new Error('molFindAnalogsWithActivity: no HTTP route available yet')
}

export function molDedupBatch(
  _newMols: Array<[string, string]>,
  _sameAsThreshold = 0.95,
): Promise<DedupResult> {
  throw new Error('molDedupBatch: no HTTP route available yet')
}

export function molSearchSubstructure(
  _querySmiles: string,
  _tanimotoThreshold?: number,
): Promise<SubstructureMatch[]> {
  throw new Error('molSearchSubstructure: no HTTP route available yet')
}
