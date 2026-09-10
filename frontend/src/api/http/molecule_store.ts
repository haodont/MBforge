/** Molecule location and correction queries. */

import { httpGet, invokeWithError } from './_utils'
import { ErrorCode } from '@/utils/errors'

export interface MoleculeLocationMatch {
  mol_id: string | null
  canonical_smiles: string
  name: string
  confidence: number | null
  page: number
  bbox: { x0: number; y0: number; x1: number; y1: number } | null
  crop_url: string | null
}

export async function moleculeByLocation(
  libraryRoot: string,
  docId: string,
  page: number,
  bbox: [number, number, number, number],
): Promise<MoleculeLocationMatch[]> {
  const params = new URLSearchParams({
    library_root: libraryRoot,
    doc_id: docId,
    page: String(page),
    x0: String(bbox[0]),
    y0: String(bbox[1]),
    x1: String(bbox[2]),
    y1: String(bbox[3]),
  })
  const response = await invokeWithError(
    () => httpGet<{ success: boolean; matches: MoleculeLocationMatch[] }>(
      `/api/v1/molecule/by-location?${params.toString()}`,
    ),
    ErrorCode.MoleculeSearch,
  )
  return response.matches
}

export interface MoleculeCorrection {
  correction_id: number
  mol_id: string
  field: string
  old_value: string | null
  new_value: string | null
  source: string
  created_at: string
}

export async function moleculeCorrections(
  libraryRoot: string,
  molId: string,
): Promise<MoleculeCorrection[]> {
  const params = new URLSearchParams({ library_root: libraryRoot })
  const response = await invokeWithError(
    () => httpGet<{ success: boolean; corrections: MoleculeCorrection[] }>(
      `/api/v1/molecule/${encodeURIComponent(molId)}/corrections?${params.toString()}`,
    ),
    ErrorCode.MoleculeSearch,
  )
  return response.corrections
}
