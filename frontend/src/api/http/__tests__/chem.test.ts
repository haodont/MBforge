import { describe, it, expect, vi, beforeEach } from 'vitest'

vi.mock('../_utils', () => ({
  httpPost: vi.fn(),
  httpGet: vi.fn(),
  httpPut: vi.fn(),
  httpDelete: vi.fn(),
  invokeWithError: vi.fn((_fn: () => Promise<unknown>) => _fn()),
}))

import { httpPost } from '../_utils'
import {
  chemValidateSmiles,
  chemTanimotoSimilarity,
  chemTanimotoBatchFilter,
  type SmilesValidation,
} from '../molecule'

const mockHttpPost = vi.mocked(httpPost)

describe('chem API (HTTP chematic)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  describe('chemValidateSmiles', () => {
    it('returns valid result for a known SMILES', async () => {
      const stub: SmilesValidation = {
        valid: true,
        canonical_smiles: 'CCO',
        error: null,
      }
      mockHttpPost.mockResolvedValue([stub])

      const result = await chemValidateSmiles('CCO')

      expect(result.valid).toBe(true)
      expect(result.canonical_smiles).toBe('CCO')
      expect(httpPost).toHaveBeenCalledWith('/api/v1/chem/validate-smiles', { smiles: 'CCO' })
    })

    it('returns invalid result with error for malformed SMILES', async () => {
      const stub: SmilesValidation = {
        valid: false,
        canonical_smiles: null,
        error: 'SMILES parse failed: UnexpectedEnd',
      }
      mockHttpPost.mockResolvedValue([stub])

      const result = await chemValidateSmiles('XYZ[')

      expect(result.valid).toBe(false)
      expect(result.canonical_smiles).toBeNull()
      expect(result.error).toMatch(/parse failed/)
    })
  })

  describe('chemTanimotoSimilarity', () => {
    it('passes both SMILES and returns f64 in [0, 1]', async () => {
      mockHttpPost.mockResolvedValue({ similarity: 1.0 })

      const result = await chemTanimotoSimilarity('CCO', 'CCO')

      expect(result).toBe(1.0)
      expect(httpPost).toHaveBeenCalledWith('/api/v1/chem/tanimoto', {
        smiles_a: 'CCO',
        smiles_b: 'CCO',
      })
    })

    it('returns low similarity for distinct molecules', async () => {
      mockHttpPost.mockResolvedValue({ similarity: 0.05 })

      const result = await chemTanimotoSimilarity('CCO', 'c1ccccc1')

      expect(result).toBeLessThan(0.5)
    })
  })

  describe('chemTanimotoBatchFilter', () => {
    it('forwards query, candidates, threshold and parses result', async () => {
      const stub: Array<[string, string, number]> = [
        ['mol1', 'CCN', 0.9],
        ['mol2', 'c1ccccc1', 0.2],
      ]
      mockHttpPost.mockResolvedValue(stub)

      const result = await chemTanimotoBatchFilter('CCO', [
        ['mol1', 'CCN'],
        ['mol2', 'c1ccccc1'],
      ], 0.5)

      expect(result).toHaveLength(2)
      expect(result[0][0]).toBe('mol1')
      expect(result[0][2]).toBeGreaterThan(0.5)
      expect(httpPost).toHaveBeenCalledWith('/api/v1/chem/substructure-search', {
        query: 'CCO',
        candidates: [
          ['mol1', 'CCN'],
          ['mol2', 'c1ccccc1'],
        ],
        threshold: 0.5,
      })
    })

    it('uses default threshold 0.5 when omitted', async () => {
      mockHttpPost.mockResolvedValue([] as never)

      await chemTanimotoBatchFilter('CCO', [['x', 'C']])

      expect(httpPost).toHaveBeenCalledWith('/api/v1/chem/substructure-search', {
        query: 'CCO',
        candidates: [['x', 'C']],
        threshold: 0.5,
      })
    })
  })
})
