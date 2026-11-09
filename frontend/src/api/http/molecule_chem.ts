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

