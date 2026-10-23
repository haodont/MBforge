/**
 * molecule.ts (chem facade) — `chemValidateSmiles` / `validateSmiles` /
 * `chemTanimotoSimilarity` (covered functions at top).
 *
 * One usage test: the only behavior worth protecting here is the SMILES
 * validation contract — a one-item array envelope, the guard against an
 * unexpected result count, and the mapping of a failed validation into the
 * `{valid, canonical_smiles, issues}` shape the UI consumes.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'

vi.mock('../_utils', () => ({
  httpPost: vi.fn(),
  httpGet: vi.fn(),
  httpPut: vi.fn(),
  httpDelete: vi.fn(),
  invokeWithError: vi.fn((_fn: () => Promise<unknown>) => _fn()),
}))

import { httpPost } from '../_utils'
import { chemValidateSmiles, chemTanimotoSimilarity, validateSmiles } from '../molecule'

const mockHttpPost = vi.mocked(httpPost)

describe('chem API (HTTP chematic)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('unwraps the one-item validation array and maps failures to ValidationIssues', async () => {
    // Valid SMILES: the array envelope is unwrapped into a bare result.
    mockHttpPost.mockResolvedValue([{ valid: true, canonical_smiles: 'CCO', error: null }])
    await expect(chemValidateSmiles('CCO')).resolves.toEqual({
      valid: true,
      canonical_smiles: 'CCO',
      error: null,
    })
    expect(httpPost).toHaveBeenCalledWith('/api/v1/chem/validate-smiles', { smiles: 'CCO' })

    // Malformed SMILES: the backend error is preserved for the caller.
    mockHttpPost.mockResolvedValue([
      { valid: false, canonical_smiles: null, error: 'SMILES parse failed: UnexpectedEnd' },
    ])
    await expect(chemValidateSmiles('XYZ[')).resolves.toMatchObject({
      valid: false,
      canonical_smiles: null,
      error: expect.stringMatching(/parse failed/),
    })

    // `validateSmiles` turns the raw error into a SYNTAX issue for the UI.
    await expect(validateSmiles('XYZ[')).resolves.toEqual({
      valid: false,
      canonical_smiles: null,
      issues: [{ code: 'SYNTAX', severity: 'error', message: 'SMILES parse failed: UnexpectedEnd' }],
    })

    // A response that is not exactly one item must fail loudly, not silently
    // pick a half-parsed result.
    mockHttpPost.mockResolvedValue([
      { valid: true, canonical_smiles: 'CCO', error: null },
      { valid: true, canonical_smiles: 'CCO', error: null },
    ])
    await expect(chemValidateSmiles('CCO')).rejects.toThrow('unexpected result count')

    // Similarity unwraps the `{similarity}` envelope.
    mockHttpPost.mockResolvedValue({ similarity: 1.0 })
    await expect(chemTanimotoSimilarity('CCO', 'CCO')).resolves.toBe(1.0)
  })
})
