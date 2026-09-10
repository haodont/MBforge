import { describe, it, expect, vi, beforeEach } from 'vitest'

vi.mock('../_utils', () => ({
  httpPost: vi.fn(),
  httpGet: vi.fn(),
  httpPut: vi.fn(),
  httpDelete: vi.fn(),
  invokeWithError: vi.fn((_fn: () => Promise<unknown>) => _fn()),
  ErrorCode: { ApiError: 'ApiError', Network: 'Network', Unknown: 'Unknown', MoleculeSearch: 'MoleculeSearch' },
}))

import { httpPost } from '../_utils'
import {
  sarBuildMatrix,
  sarHeatmap,
  type RGroupMatrix,
  type ActivityHeatmap,
  type CompoundInput,
} from '../sar'

const mockHttpPost = vi.mocked(httpPost)

describe('sar API', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  describe('sarBuildMatrix', () => {
    const compounds: CompoundInput[] = [
      { id: 'mol1', name: 'A', smiles: 'c1ccc(CC(=O)O)cc1', activity: 1.2 },
      { id: 'mol2', name: 'B', smiles: 'c1ccc(CC(=O)N)cc1', activity: 2.4 },
    ]

    it('calls httpPost with compounds and explicit coreSmiles', async () => {
      const stub: RGroupMatrix = {
        core_smiles: 'c1ccccc1',
        r_labels: ['R1'],
        rows: [['CC(=O)O'], ['CC(=O)N']],
        compounds: [
          { id: 'mol1', name: 'A', smiles: 'c1ccc(CC(=O)O)cc1', activity: 1.2, matches: true },
          { id: 'mol2', name: 'B', smiles: 'c1ccc(CC(=O)N)cc1', activity: 2.4, matches: true },
        ],
        unmatched_count: 0,
      }
      mockHttpPost.mockResolvedValue(stub)

      const result = await sarBuildMatrix(compounds, 'c1ccccc1')

      expect(result).toEqual(stub)
      expect(httpPost).toHaveBeenCalledTimes(1)
      expect(httpPost).toHaveBeenCalledWith('/api/v1/sar/build-matrix', {
        compounds,
        coreSmiles: 'c1ccccc1',
      })
    })

    it('passes null for coreSmiles when omitted', async () => {
      const stub: RGroupMatrix = {
        core_smiles: '',
        r_labels: [],
        rows: [],
        compounds: [
          { id: 'mol1', name: 'A', smiles: 'c1ccc(CC(=O)O)cc1', matches: false },
          { id: 'mol2', name: 'B', smiles: 'c1ccc(CC(=O)N)cc1', matches: false },
        ],
        unmatched_count: 2,
      }
      mockHttpPost.mockResolvedValue(stub)

      const result = await sarBuildMatrix(compounds)

      expect(result).toEqual(stub)
      expect(httpPost).toHaveBeenCalledTimes(1)
      expect(httpPost).toHaveBeenCalledWith('/api/v1/sar/build-matrix', {
        compounds,
        coreSmiles: null,
      })
    })

    it('propagates httpPost rejection', async () => {
      mockHttpPost.mockRejectedValue(new Error('matrix failed'))

      await expect(sarBuildMatrix(compounds)).rejects.toThrow('matrix failed')
      expect(httpPost).toHaveBeenCalledTimes(1)
    })
  })

  describe('sarHeatmap', () => {
    const matrix: RGroupMatrix = {
      core_smiles: 'c1ccccc1',
      r_labels: ['R1'],
      rows: [['CC(=O)O'], ['CC(=O)N']],
      compounds: [
        { id: 'mol1', name: 'A', smiles: 'c1ccc(CC(=O)O)cc1', activity: 1.2, matches: true },
        { id: 'mol2', name: 'B', smiles: 'c1ccc(CC(=O)N)cc1', activity: 2.4, matches: true },
      ],
      unmatched_count: 0,
    }

    it('calls httpPost with matrix and lowerIsBetter true by default', async () => {
      const stub: ActivityHeatmap[] = [
        {
          r_label: 'R1',
          cells: [
            { substituent_smiles: 'CC(=O)O', avg_activity: 1.2, count: 1, min: 1.2, max: 1.2 },
            { substituent_smiles: 'CC(=O)N', avg_activity: 2.4, count: 1, min: 2.4, max: 2.4 },
          ],
        },
      ]
      mockHttpPost.mockResolvedValue(stub)

      const result = await sarHeatmap(matrix)

      expect(result).toEqual(stub)
      expect(httpPost).toHaveBeenCalledTimes(1)
      expect(httpPost).toHaveBeenCalledWith('/api/v1/sar/heatmap', {
        matrix,
        lowerIsBetter: true,
      })
    })

    it('passes explicit lowerIsBetter value', async () => {
      mockHttpPost.mockResolvedValue([] as never)

      await sarHeatmap(matrix, false)

      expect(httpPost).toHaveBeenCalledTimes(1)
      expect(httpPost).toHaveBeenCalledWith('/api/v1/sar/heatmap', {
        matrix,
        lowerIsBetter: false,
      })
    })

    it('propagates httpPost rejection', async () => {
      mockHttpPost.mockRejectedValue(new Error('heatmap failed'))

      await expect(sarHeatmap(matrix)).rejects.toThrow('heatmap failed')
      expect(httpPost).toHaveBeenCalledTimes(1)
    })
  })
})
