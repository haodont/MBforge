/**
 * molecule_admin.ts — molecule CRUD HTTP wrappers (covered module at top).
 *
 * One usage test over the mocked `_utils` boundary: it protects the response
 * envelopes that are actually *transformed* (list param normalisation, search
 * result unwrapping, the single-item SMILES validation array) and the
 * request payload shapes the backend routes require (create subset,
 * PUT record/status, DELETE body).
 */

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

  it('transforms list/search/validation envelopes and preserves the backend payload contract', async () => {
    // --- read: list normalisation (offset→page, defaults for absent filters)
    mockHttpPost.mockResolvedValue({ success: true, items: [mockRecord], total: 1 })
    await expect(molAdminList('/project', 10, 0, 'patent', 'pending')).resolves.toEqual([mockRecord])
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

    mockHttpPost.mockResolvedValue({ success: true, items: [], total: 0 })
    await molAdminList('/project', 5, 0)
    expect(httpPost).toHaveBeenLastCalledWith('/api/v1/molecule/list', {
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

    // --- read: exact-SMILES search unwraps the first hit, text search keeps all
    mockHttpPost.mockResolvedValue({ success: true, results: [mockRecord, { ...mockRecord, mol_id: 'mol-2' }] })
    await expect(molAdminSearchBySmiles('/project', 'CCO')).resolves.toEqual(mockRecord)
    expect(httpPost).toHaveBeenLastCalledWith('/api/v1/molecule/search', {
      library_root: '/project',
      query: 'CCO',
    })

    await expect(molAdminSearchText('/project', 'ethanol')).resolves.toHaveLength(2)
    expect(httpPost).toHaveBeenLastCalledWith('/api/v1/molecule/search', {
      library_root: '/project',
      query: 'ethanol',
    })

    // --- read: single-record fetch reports "not found" as null, errors propagate
    mockHttpPost.mockResolvedValue({ success: true, molecule: mockRecord })
    await expect(molAdminGet('/project', 'mol-1')).resolves.toEqual(mockRecord)
    mockHttpPost.mockResolvedValue({ success: false })
    await expect(molAdminGet('/project', 'missing')).resolves.toBeNull()
    mockHttpPost.mockRejectedValue(new Error('db locked'))
    await expect(molAdminGet('/project', 'mol-1')).rejects.toThrow('db locked')

    // --- SMILES validation unwraps the one-item array into {valid, canonical_smiles, issues}
    mockHttpPost.mockResolvedValue([{ valid: true, canonical_smiles: 'CCO', error: null }])
    await expect(validateSmiles('CCO')).resolves.toEqual({
      valid: true,
      canonical_smiles: 'CCO',
      issues: [],
    })

    // --- write: create sends the subset of record fields the route accepts
    mockHttpPost.mockResolvedValue(undefined)
    await molAdminAdd('/project', mockRecord)
    expect(httpPost).toHaveBeenLastCalledWith('/api/v1/molecule/create', {
      library_root: '/project',
      mol_id: 'mol-1',
      smiles: 'CCO',
      esmiles: 'CCO',
      name: 'ethanol',
      source_type: 'patent',
    })

    // --- write: full update PUTs the whole record, status update PUTs only status
    mockHttpPut.mockResolvedValue({ success: true })
    await expect(molAdminUpdate('/project', mockRecord)).resolves.toBe(true)
    expect(httpPut).toHaveBeenCalledWith('/api/v1/molecule/mol-1', {
      library_root: '/project',
      ...mockRecord,
    })

    await expect(molAdminUpdateStatus('/project', 'mol-1', 'confirmed')).resolves.toBe(true)
    expect(httpPut).toHaveBeenLastCalledWith('/api/v1/molecule/mol-1', {
      library_root: '/project',
      status: 'confirmed',
    })

    // --- write: delete sends the library root in the body
    mockHttpDelete.mockResolvedValue({ success: true })
    await expect(molAdminDelete('/project', 'mol-1')).resolves.toBe(true)
    expect(httpDelete).toHaveBeenCalledWith('/api/v1/molecule/mol-1', {
      library_root: '/project',
    })
  })
})
