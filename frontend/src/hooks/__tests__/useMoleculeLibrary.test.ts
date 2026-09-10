import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook, waitFor, act } from '@testing-library/react'
import { useMoleculeLibrary } from '../useMoleculeLibrary'

vi.mock('@/api/http/molecule_admin', () => ({
  molAdminListPage: vi.fn(),
}))

import { molAdminListPage } from '@/api/http/molecule_admin'

const mockMolecule = {
  mol_id: 'm1',
  name: 'A',
  esmiles: 'C',
  status: 'confirmed',
  activity: 10,
  activity_type: 'IC50',
  units: 'nM',
  source_doc: 'doc1',
  source_type: 'text',
  properties: {},
  tags: [],
  notes: '',
  created_at: '2026-01-01',
}

describe('useMoleculeLibrary', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('loads molecules on mount', async () => {
    const molecules = [mockMolecule]
    const mockList = molAdminListPage as ReturnType<typeof vi.fn>
    mockList.mockResolvedValue({ items: molecules, total: 1, matching_ids: ['m1'], source_types: ['text'], source_docs: ['doc1'] })

    const { result } = renderHook(() => useMoleculeLibrary('/project'))

    expect(result.current.loading).toBe(true)
    await waitFor(() => expect(result.current.loading).toBe(false))
    expect(result.current.molecules).toEqual(molecules)
    expect(result.current.totalCount).toBe(1)
    expect(result.current.error).toBeNull()
  })

  it('toggles selection', async () => {
    const molecules = [mockMolecule]
    const mockList = molAdminListPage as ReturnType<typeof vi.fn>
    mockList.mockResolvedValue({ items: molecules, total: 1, matching_ids: ['m1'], source_types: ['text'], source_docs: ['doc1'] })

    const { result } = renderHook(() => useMoleculeLibrary('/project'))
    await waitFor(() => expect(result.current.loading).toBe(false))

    act(() => {
      result.current.toggleSelection('m1')
    })
    expect(result.current.selectedIds.has('m1')).toBe(true)

    act(() => {
      result.current.toggleSelection('m1')
    })
    expect(result.current.selectedIds.has('m1')).toBe(false)
  })

  it('clears selection', async () => {
    const molecules = [
      mockMolecule,
      { ...mockMolecule, mol_id: 'm2', name: 'B' },
    ]
    const mockList = molAdminListPage as ReturnType<typeof vi.fn>
    mockList.mockResolvedValue({ items: molecules, total: molecules.length, matching_ids: molecules.map((m) => m.mol_id), source_types: ['text'], source_docs: ['doc1'] })

    const { result } = renderHook(() => useMoleculeLibrary('/project'))
    await waitFor(() => expect(result.current.loading).toBe(false))

    act(() => {
      result.current.selectAll()
    })
    expect(result.current.selectedIds.size).toBe(2)

    act(() => {
      result.current.clearSelection()
    })
    expect(result.current.selectedIds.size).toBe(0)
  })

  it('selects all matching results beyond the current page', async () => {
    const molecules = [
      mockMolecule,
      { ...mockMolecule, mol_id: 'm2', name: 'B' },
    ]
    const mockList = molAdminListPage as ReturnType<typeof vi.fn>
    mockList
      .mockResolvedValueOnce({ items: molecules, total: 2, matching_ids: ['m1', 'm2'], source_types: ['text'], source_docs: ['doc1'] })
      .mockResolvedValueOnce({ items: [molecules[0]], total: 2, matching_ids: ['m1', 'm2'], source_types: ['text'], source_docs: ['doc1'] })

    const { result } = renderHook(() => useMoleculeLibrary('/project'))
    await waitFor(() => expect(result.current.loading).toBe(false))

    act(() => {
      result.current.setPagination({ page: 1, pageSize: 1 })
    })
    await waitFor(() => expect(result.current.molecules).toHaveLength(1))

    act(() => {
      result.current.selectAllResults?.()
    })
    expect(result.current.selectedIds).toEqual(new Set(['m1', 'm2']))
  })

  it('filters records that still need activity data', async () => {
    const molecules = [
      mockMolecule,
      { ...mockMolecule, mol_id: 'm2', name: 'B', activity: null },
    ]
    const mockList = molAdminListPage as ReturnType<typeof vi.fn>
    mockList
      .mockResolvedValueOnce({ items: molecules, total: 2, matching_ids: ['m1', 'm2'], source_types: ['text'], source_docs: ['doc1'] })
      .mockResolvedValueOnce({ items: [molecules[1]], total: 1, matching_ids: ['m2'], source_types: ['text'], source_docs: ['doc1'] })

    const { result } = renderHook(() => useMoleculeLibrary('/project'))
    await waitFor(() => expect(result.current.loading).toBe(false))

    act(() => {
      result.current.setFilters((previous) => ({
        ...previous,
        activityPresence: 'missing',
      }))
    })

    await waitFor(() => expect(result.current.totalCount).toBe(1))
    expect(result.current.molecules.map((item) => item.mol_id)).toEqual(['m2'])
  })
})
