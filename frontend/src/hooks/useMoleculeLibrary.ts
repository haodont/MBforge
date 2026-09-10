import { useCallback, useEffect, useState } from 'react'
import { molAdminListPage } from '@/api/http/molecule_admin'
import type { MoleculeRecord } from '@/types'

export type MoleculeStatusFilter = 'all' | 'confirmed' | 'pending' | 'rejected' | 'corrected'
export type MoleculeActivityFilter = 'all' | 'present' | 'missing'
export type MoleculeViewMode = 'table' | 'card'
export type MoleculeSortField = 'name' | 'activity' | 'status' | 'created_at'
export type MoleculeSortDirection = 'asc' | 'desc'

export interface MoleculeFilters {
  status: MoleculeStatusFilter
  sourceType: string
  sourceDoc: string
  activityPresence: MoleculeActivityFilter
  activityMin: number | null
  activityMax: number | null
}

export interface MoleculePagination {
  page: number
  pageSize: number
}

export interface MoleculeSort {
  field: MoleculeSortField
  direction: MoleculeSortDirection
}

export interface UseMoleculeLibraryResult {
  molecules: MoleculeRecord[]
  totalCount: number
  loading: boolean
  error: string | null
  info: string | null
  query: string
  filters: MoleculeFilters
  sort: MoleculeSort
  pagination: MoleculePagination
  viewMode: MoleculeViewMode
  selectedIds: Set<string>
  matchingIds?: string[]
  sourceTypeOptions: string[]
  sourceDocOptions: string[]

  setQuery: (q: string) => void
  setFilters: React.Dispatch<React.SetStateAction<MoleculeFilters>>
  setSort: (sort: MoleculeSort) => void
  setPagination: React.Dispatch<React.SetStateAction<MoleculePagination>>
  setViewMode: (mode: MoleculeViewMode) => void
  toggleSelection: (molId: string) => void
  selectRange: (startId: string, endId: string) => void
  selectCurrentPage?: () => void
  selectAllResults?: () => void
  selectAll: () => void
  clearSelection: () => void
  refresh: () => void
}

const VIEW_MODE_KEY = 'mbforge_molecule_view_mode'

export function useMoleculeLibrary(libraryRoot: string | null): UseMoleculeLibraryResult {
  const [molecules, setMolecules] = useState<MoleculeRecord[]>([])
  const [totalCount, setTotalCount] = useState(0)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [info, setInfo] = useState<string | null>(null)
  const [query, setQueryState] = useState('')
  const [debouncedQuery, setDebouncedQuery] = useState(query)
  const [filters, setFiltersState] = useState<MoleculeFilters>({
    status: 'all',
    sourceType: 'all',
    sourceDoc: 'all',
    activityPresence: 'present',
    activityMin: null,
    activityMax: null,
  })
  const [sort, setSortState] = useState<MoleculeSort>({ field: 'created_at', direction: 'desc' })
  const [pagination, setPaginationState] = useState<MoleculePagination>({ page: 1, pageSize: 50 })
  const [viewMode, setViewModeState] = useState<MoleculeViewMode>(() => {
    const saved = localStorage.getItem(VIEW_MODE_KEY)
    return saved === 'card' ? 'card' : 'table'
  })
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())
  const [matchingIds, setMatchingIds] = useState<string[]>([])
  const [sourceTypeOptions, setSourceTypeOptions] = useState<string[]>([])
  const [sourceDocOptions, setSourceDocOptions] = useState<string[]>([])

  useEffect(() => {
    const timer = setTimeout(() => setDebouncedQuery(query), 250)
    return () => clearTimeout(timer)
  }, [query])

  const setQuery = useCallback((q: string) => {
    setQueryState(q)
    setPaginationState((prev) => ({ ...prev, page: 1 }))
  }, [])

  const setFilters = useCallback((update: React.SetStateAction<MoleculeFilters>) => {
    setFiltersState(update)
    setPaginationState((prev) => ({ ...prev, page: 1 }))
  }, [])

  const setSort = useCallback((nextSort: MoleculeSort) => {
    setSortState(nextSort)
    setPaginationState((prev) => ({ ...prev, page: 1 }))
  }, [])

  const setPagination = useCallback((update: React.SetStateAction<MoleculePagination>) => {
    setPaginationState((prev) => {
      const next = typeof update === 'function' ? update(prev) : update
      return next.pageSize !== prev.pageSize ? { ...next, page: 1 } : next
    })
  }, [])

  const setViewMode = useCallback((mode: MoleculeViewMode) => {
    localStorage.setItem(VIEW_MODE_KEY, mode)
    setViewModeState(mode)
  }, [])

  const load = useCallback(async () => {
    if (!libraryRoot) {
      setMolecules([])
      setTotalCount(0)
      setMatchingIds([])
      return
    }
    setLoading(true)
    setError(null)
    try {
      const response = await molAdminListPage(libraryRoot, {
        page: pagination.page,
        pageSize: pagination.pageSize,
        status: filters.status === 'all' ? undefined : filters.status,
        sourceType: filters.sourceType === 'all' ? undefined : filters.sourceType,
        sourceDoc: filters.sourceDoc === 'all' ? undefined : filters.sourceDoc,
        activityPresence: filters.activityPresence,
        activityMin: filters.activityMin,
        activityMax: filters.activityMax,
        query: debouncedQuery.trim(),
        sortField: sort.field,
        sortDirection: sort.direction,
      })

      setMolecules(response.items)
      setTotalCount(response.total)
      setMatchingIds(response.matching_ids)
      setSourceTypeOptions(response.source_types)
      setSourceDocOptions(response.source_docs)
      setInfo(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : '加载分子失败')
      setInfo(null)
      setMolecules([])
      setTotalCount(0)
      setMatchingIds([])
    } finally {
      setLoading(false)
    }
  }, [libraryRoot, debouncedQuery, filters, sort, pagination.page, pagination.pageSize])

  useEffect(() => {
    void load()
  }, [load])

  const toggleSelection = useCallback((molId: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev)
      if (next.has(molId)) next.delete(molId)
      else next.add(molId)
      return next
    })
  }, [])

  const selectRange = useCallback((startId: string, endId: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev)
      const startIdx = molecules.findIndex((m) => m.mol_id === startId)
      const endIdx = molecules.findIndex((m) => m.mol_id === endId)
      if (startIdx === -1 || endIdx === -1) return prev
      const [low, high] = startIdx < endIdx ? [startIdx, endIdx] : [endIdx, startIdx]
      for (let i = low; i <= high; i++) {
        next.add(molecules[i].mol_id)
      }
      return next
    })
  }, [molecules])

  const selectCurrentPage = useCallback(() => {
    setSelectedIds((prev) => {
      const next = new Set(prev)
      molecules.forEach((m) => next.add(m.mol_id))
      return next
    })
  }, [molecules])

  const selectAllResults = useCallback(() => {
    setSelectedIds(new Set(matchingIds))
  }, [matchingIds])

  const clearSelection = useCallback(() => {
    setSelectedIds(new Set())
  }, [])

  return {
    molecules,
    totalCount,
    loading,
    error,
    info,
    query,
    filters,
    sort,
    pagination,
    viewMode,
    selectedIds,
    matchingIds,
    sourceTypeOptions,
    sourceDocOptions,
    setQuery,
    setFilters,
    setSort,
    setPagination,
    setViewMode,
    toggleSelection,
    selectRange,
    selectCurrentPage,
    selectAllResults,
    selectAll: selectAllResults,
    clearSelection,
    refresh: load,
  }
}
