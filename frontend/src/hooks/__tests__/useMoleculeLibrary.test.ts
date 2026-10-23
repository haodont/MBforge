/**
 * useMoleculeLibrary.ts — molecule library hook (covered module at top).
 *
 * Protects the state transitions that callers depend on: the mount fetch
 * populating data/metadata, selection management (toggle / select-all /
 * clear / select-all-results beyond the current page) and filter-driven
 * refetches.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook, waitFor, act } from '@testing-library/react'
import { QueryClientProvider } from '@tanstack/react-query'
import { createElement, type ReactNode } from 'react'
import { useMoleculeLibrary } from '../useMoleculeLibrary'
import { createQueryClient } from '@/api/query/client'
import type { MoleculeRecord } from '@/types'

vi.mock('@/api/http/molecule_admin', () => ({
  molAdminListPage: vi.fn(),
}))

import { molAdminListPage } from '@/api/http/molecule_admin'

const mockList = vi.mocked(molAdminListPage)

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

const secondMolecule = { ...mockMolecule, mol_id: 'm2', name: 'B' }

function renderLibrary(root: string) {
  const client = createQueryClient()
  return renderHook(() => useMoleculeLibrary(root), {
    wrapper: ({ children }: { children: ReactNode }) =>
      createElement(QueryClientProvider, { client }, children),
  })
}

function page(
  items: MoleculeRecord[],
  total: number,
  matchingIds: string[],
) {
  return {
    items,
    total,
    matching_ids: matchingIds,
    source_types: ['text'],
    source_docs: ['doc1'],
  }
}

describe('useMoleculeLibrary', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('loads molecules on mount and manages selection', async () => {
    mockList.mockResolvedValue(page([mockMolecule, secondMolecule], 2, ['m1', 'm2']))

    const { result } = renderLibrary('/project')

    expect(result.current.loading).toBe(true)
    await waitFor(() => expect(result.current.loading).toBe(false))
    expect(result.current.molecules).toEqual([mockMolecule, secondMolecule])
    expect(result.current.totalCount).toBe(2)
    expect(result.current.error).toBeNull()

    act(() => {
      result.current.toggleSelection('m1')
    })
    expect(result.current.selectedIds.has('m1')).toBe(true)

    act(() => {
      result.current.toggleSelection('m1')
    })
    expect(result.current.selectedIds.has('m1')).toBe(false)

    act(() => {
      result.current.selectAll()
    })
    expect(result.current.selectedIds.size).toBe(2)

    act(() => {
      result.current.clearSelection()
    })
    expect(result.current.selectedIds.size).toBe(0)
  })

  it('selects all matching results beyond the current page and refetches on filter change', async () => {
    mockList
      .mockResolvedValueOnce(page([mockMolecule, secondMolecule], 2, ['m1', 'm2']))
      .mockResolvedValueOnce(page([mockMolecule], 2, ['m1', 'm2']))
      .mockResolvedValueOnce(page([{ ...secondMolecule, activity: null }], 1, ['m2']))

    const { result } = renderLibrary('/project')
    await waitFor(() => expect(result.current.loading).toBe(false))

    act(() => {
      result.current.setPagination({ page: 1, pageSize: 1 })
    })
    await waitFor(() => expect(result.current.molecules).toHaveLength(1))

    // Selection follows the server-reported match set, not just the page.
    act(() => {
      result.current.selectAllResults?.()
    })
    expect(result.current.selectedIds).toEqual(new Set(['m1', 'm2']))

    // A filter change refetches and replaces the visible rows.
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
