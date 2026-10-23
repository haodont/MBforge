/**
 * sar.ts — SAR analysis wrappers (covered module at top).
 *
 * The contract worth protecting is the request body the backend expects:
 * `coreSmiles` must be sent explicitly as `null` when unspecified (a missing
 * key is not the same as "no core"), `lowerIsBetter` defaults to true, and
 * backend failures surface to the caller.
 */

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
import { sarBuildMatrix, sarHeatmap, type RGroupMatrix, type CompoundInput } from '../sar'

const mockHttpPost = vi.mocked(httpPost)

const compounds: CompoundInput[] = [
  { id: 'mol1', name: 'A', smiles: 'c1ccc(CC(=O)O)cc1', activity: 1.2 },
  { id: 'mol2', name: 'B', smiles: 'c1ccc(CC(=O)N)cc1', activity: 2.4 },
]

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

describe('sar API', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('sends compounds with an explicit coreSmiles and default heatmap orientation', async () => {
    mockHttpPost.mockResolvedValue(matrix)
    await expect(sarBuildMatrix(compounds, 'c1ccccc1')).resolves.toEqual(matrix)
    expect(httpPost).toHaveBeenCalledWith('/api/v1/sar/build-matrix', {
      compounds,
      coreSmiles: 'c1ccccc1',
    })

    // Omitted core must serialize as an explicit null, not a missing key.
    await sarBuildMatrix(compounds)
    expect(httpPost).toHaveBeenLastCalledWith('/api/v1/sar/build-matrix', {
      compounds,
      coreSmiles: null,
    })

    // Heatmap defaults to lowerIsBetter=true (activity columns are IC50-like).
    const heatmap = [{
      r_label: 'R1',
      cells: [{ substituent_smiles: 'CC(=O)O', avg_activity: 1.2, count: 1, min: 1.2, max: 1.2 }],
    }]
    mockHttpPost.mockResolvedValue(heatmap)
    await expect(sarHeatmap(matrix)).resolves.toEqual(heatmap)
    expect(httpPost).toHaveBeenLastCalledWith('/api/v1/sar/heatmap', { matrix, lowerIsBetter: true })

    await sarHeatmap(matrix, false)
    expect(httpPost).toHaveBeenLastCalledWith('/api/v1/sar/heatmap', { matrix, lowerIsBetter: false })

    // Backend failures reach the caller instead of being swallowed.
    mockHttpPost.mockRejectedValue(new Error('matrix failed'))
    await expect(sarBuildMatrix(compounds)).rejects.toThrow('matrix failed')
    mockHttpPost.mockRejectedValue(new Error('heatmap failed'))
    await expect(sarHeatmap(matrix)).rejects.toThrow('heatmap failed')
  })
})
