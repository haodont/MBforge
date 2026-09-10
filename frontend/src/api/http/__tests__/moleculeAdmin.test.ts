import { describe, it, expect, vi, beforeEach } from 'vitest'

vi.mock('../_utils', () => ({
  httpPost: vi.fn(),
  httpGet: vi.fn(),
  httpPut: vi.fn(),
  httpDelete: vi.fn(),
  invokeWithError: vi.fn((_fn: () => Promise<unknown>) => _fn()),
}))

import { httpPost, httpPut, httpDelete } from '../_utils'
import {
  molAdminGet,
  molAdminSearchBySmiles,
  molAdminSearchText,
  molAdminList,
  molAdminStoreStats,
  molAdminCheckMarkush,
  molAdminParseEsmiles,
  molAdminAdd,
  molAdminUpdate,
  molAdminUpdateStatus,
  molAdminDelete,
} from '../molecule_admin'
import { validateSmiles } from '../molecule'

const mockHttpPost = vi.mocked(httpPost)
const mockHttpPut = vi.mocked(httpPut)
const mockHttpDelete = vi.mocked(httpDelete)

const mockRecord = {
  mol_id: 'mol-1',
  esmiles: 'CCO',
  name: 'ethanol',
  source_doc: 'doc-1',
  source_type: 'patent',
  activity: null,
  activity_type: '',
  units: '',
  status: 'pending',
  properties: {},
  tags: [],
  notes: '',
  created_at: '2026-06-15T00:00:00Z',
}

describe('moleculeAdmin API', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  describe('molAdminGet', () => {
    it('calls httpPost with correct params', async () => {
      mockHttpPost.mockResolvedValue({ success: true, molecule: mockRecord })

      const result = await molAdminGet('/project', 'mol-1')

      expect(httpPost).toHaveBeenCalledWith('/api/v1/molecule/get', {
        library_root: '/project',
        mol_id: 'mol-1',
      })
      expect(result).toEqual(mockRecord)
    })

    it('returns null when molecule not found', async () => {
      mockHttpPost.mockResolvedValue({ success: false })

      const result = await molAdminGet('/project', 'missing')

      expect(result).toBeNull()
    })

    it('propagates httpPost errors', async () => {
      mockHttpPost.mockRejectedValue(new Error('db locked'))

      await expect(molAdminGet('/project', 'mol-1')).rejects.toThrow('db locked')
    })
  })

  describe('molAdminSearchBySmiles', () => {
    it('calls httpPost with correct params', async () => {
      mockHttpPost.mockResolvedValue({ success: true, results: [mockRecord] })

      const result = await molAdminSearchBySmiles('/project', 'CCO')

      expect(httpPost).toHaveBeenCalledWith('/api/v1/molecule/search', {
        library_root: '/project',
        query: 'CCO',
      })
      expect(result).toEqual(mockRecord)
    })
  })

  describe('molAdminSearchText', () => {
    it('calls httpPost with correct params', async () => {
      mockHttpPost.mockResolvedValue({ success: true, results: [mockRecord] })

      const result = await molAdminSearchText('/project', 'ethanol')

      expect(httpPost).toHaveBeenCalledWith('/api/v1/molecule/search', {
        library_root: '/project',
        query: 'ethanol',
      })
      expect(result).toEqual([mockRecord])
    })
  })

  describe('molAdminList', () => {
    it('calls httpPost with correct params', async () => {
      mockHttpPost.mockResolvedValue({ success: true, items: [mockRecord], total: 1 })

      const result = await molAdminList('/project', 10, 0, 'patent', 'pending')

      expect(httpPost).toHaveBeenCalledWith('/api/v1/molecule/list', {
        library_root: '/project',
        page: 1,
        page_size: 10,
        status: 'pending',
        source_type: 'patent',
        source_doc: '',
        activity_presence: 'all',
        activity_min: null,
        activity_max: null,
        query: '',
        sort_field: 'created_at',
        sort_direction: 'desc',
      })
      expect(result).toEqual([mockRecord])
    })

    it('works without optional filters', async () => {
      mockHttpPost.mockResolvedValue({ success: true, items: [], total: 0 })

      await molAdminList('/project', 5, 0)

      expect(httpPost).toHaveBeenCalledWith('/api/v1/molecule/list', {
        library_root: '/project',
        page: 1,
        page_size: 5,
        status: '',
        source_type: '',
        source_doc: '',
        activity_presence: 'all',
        activity_min: null,
        activity_max: null,
        query: '',
        sort_field: 'created_at',
        sort_direction: 'desc',
      })
    })
  })

  describe('SMILES validation', () => {
    it('unwraps the one-item validation array returned by the API', async () => {
      mockHttpPost.mockResolvedValue([{ valid: true, canonical_smiles: 'CCO', error: null }])

      await expect(validateSmiles('CCO')).resolves.toEqual({
        valid: true,
        canonical_smiles: 'CCO',
        issues: [],
      })
    })
  })

  describe('molAdminStoreStats', () => {
    it('calls httpPost with correct params', async () => {
      const stats = { total: 1, by_status: {} }
      mockHttpPost.mockResolvedValue(stats)

      const result = await molAdminStoreStats('/project')

      expect(httpPost).toHaveBeenCalledWith('/api/v1/molecule/stats', {
        library_root: '/project',
      })
      expect(result).toEqual(stats)
    })
  })

  describe('molAdminCheckMarkush', () => {
    it('calls httpPost with correct params', async () => {
      const overlap = {
        match_level: 'FullOverlap',
        core_overlap_ratio: 1,
        matched_core_atoms: 6,
        total_core_atoms: 6,
        r_group_results: [],
        details: [],
      }
      mockHttpPost.mockResolvedValue(overlap)

      const result = await molAdminCheckMarkush('/project', 'C*', 'CCO', 'ctx')

      expect(httpPost).toHaveBeenCalledWith('/api/v1/chem/markush-check', {
        esmiles: 'C*',
        query: 'CCO',
        ctx: 'ctx',
      })
      expect(result).toEqual(overlap)
    })

    it('works without optional ctx', async () => {
      mockHttpPost.mockResolvedValue({ match_level: 'NoOverlap' })

      await molAdminCheckMarkush('/project', 'C*', 'CCO')

      expect(httpPost).toHaveBeenCalledWith('/api/v1/chem/markush-check', {
        esmiles: 'C*',
        query: 'CCO',
        ctx: undefined,
      })
    })
  })

  describe('molAdminParseEsmiles', () => {
    it('calls httpPost with correct params', async () => {
      const pattern = {
        core_smiles: 'CCO',
        r_groups: [],
        abstract_rings: [],
        raw: 'CCO',
      }
      mockHttpPost.mockResolvedValue(pattern)

      const result = await molAdminParseEsmiles('/project', 'CCO')

      expect(httpPost).toHaveBeenCalledWith('/api/v1/chem/markush-parse', {
        input: 'CCO',
      })
      expect(result).toEqual(pattern)
    })
  })

  describe('molAdminAdd', () => {
    it('calls httpPost with correct params', async () => {
      mockHttpPost.mockResolvedValue(undefined)

      await molAdminAdd('/project', mockRecord)

      expect(httpPost).toHaveBeenCalledWith('/api/v1/molecule/create', {
        library_root: '/project',
        mol_id: 'mol-1',
        smiles: 'CCO',
        esmiles: 'CCO',
        name: 'ethanol',
        source_type: 'patent',
      })
    })
  })

  describe('molAdminUpdate', () => {
    it('calls httpPut with correct params', async () => {
      mockHttpPut.mockResolvedValue({ success: true })

      const result = await molAdminUpdate('/project', mockRecord)

      expect(httpPut).toHaveBeenCalledWith('/api/v1/molecule/mol-1', {
        library_root: '/project',
        ...mockRecord,
      })
      expect(result).toBe(true)
    })
  })

  describe('molAdminUpdateStatus', () => {
    it('calls httpPut with correct params', async () => {
      mockHttpPut.mockResolvedValue({ success: true })

      const result = await molAdminUpdateStatus('/project', 'mol-1', 'confirmed')

      expect(httpPut).toHaveBeenCalledWith('/api/v1/molecule/mol-1', {
        library_root: '/project',
        status: 'confirmed',
      })
      expect(result).toBe(true)
    })
  })

  describe('molAdminDelete', () => {
    it('calls httpDelete with correct params', async () => {
      mockHttpDelete.mockResolvedValue({ success: true })

      const result = await molAdminDelete('/project', 'mol-1')

      expect(httpDelete).toHaveBeenCalledWith('/api/v1/molecule/mol-1', {
        library_root: '/project',
      })
      expect(result).toBe(true)
    })
  })
})
