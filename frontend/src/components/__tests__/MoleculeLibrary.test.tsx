import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('@/context/AppContext', () => ({
  useAppContext: vi.fn(),
}))

vi.mock('@/hooks/useMoleculeLibrary', () => ({
  useMoleculeLibrary: vi.fn(),
}))

vi.mock('@/hooks/useMoleculeAnalysis', () => ({
  useMoleculeAnalysis: vi.fn(),
}))

vi.mock('@/components/molecule/MoleculeFilters', () => ({
  default: () => <div data-testid="molecule-filters" />,
}))

vi.mock('@/components/molecule/MoleculeTable', () => ({
  default: () => <div data-testid="molecule-table" />,
}))

vi.mock('@/components/molecule/MoleculeCardGrid', () => ({
  default: () => <div data-testid="molecule-card-grid" />,
}))

vi.mock('@/components/molecule/MoleculeAnalysisPanel', () => ({
  default: () => <div data-testid="molecule-analysis-panel" />,
}))

vi.mock('@/components/molecule/MoleculeDetailDrawer', () => ({
  default: () => null,
}))

vi.mock('@/components/ui/AddMoleculeDialog', () => ({
  AddMoleculeDialog: () => null,
}))

vi.mock('react-i18next', () => ({
  initReactI18next: { type: '3rdParty', init: () => {} },
  useTranslation: () => ({
    t: (key: string, params?: Record<string, number>) => {
      if (key === 'mol.selectionSummary') {
        return `Selected ${params?.count} / ${params?.total}`
      }
      if (key === 'common.close') return 'Close'
      if (key === 'mol.viewTable') return 'Table view'
      if (key === 'mol.viewCard') return 'Card view'
      if (key === 'mol.analyzeSelection') return 'Analyze selection'
      if (key === 'mol.hideAnalysis') return 'Hide analysis'
      if (key === 'mol.title') return 'Molecules'
      return key
    },
  }),
}))

import { useAppContext } from '@/context/AppContext'
import { useMoleculeAnalysis } from '@/hooks/useMoleculeAnalysis'
import { useMoleculeLibrary } from '@/hooks/useMoleculeLibrary'
import MoleculeLibrary from '../MoleculeLibrary'

describe('MoleculeLibrary', () => {
  let setViewMode = vi.fn()

  beforeEach(() => {
    vi.clearAllMocks()
    setViewMode = vi.fn()
    vi.mocked(useAppContext).mockReturnValue({
      libraryRoot: '/tmp/library',
    } as ReturnType<typeof useAppContext>)
    vi.mocked(useMoleculeLibrary).mockReturnValue({
      molecules: [],
      totalCount: 12,
      loading: false,
      error: null,
      info: null,
      query: '',
      filters: {
        status: 'all',
        sourceType: 'all',
        sourceDoc: 'all',
        activityPresence: 'all',
        activityMin: null,
        activityMax: null,
      },
      sort: { field: 'created_at', direction: 'desc' },
      pagination: { page: 1, pageSize: 50 },
      viewMode: 'table',
      selectedIds: new Set(['molecule-1']),
      sourceTypeOptions: [],
      sourceDocOptions: [],
      setQuery: vi.fn(),
      setFilters: vi.fn(),
      setSort: vi.fn(),
      setPagination: vi.fn(),
      setViewMode,
      toggleSelection: vi.fn(),
      selectRange: vi.fn(),
      selectAll: vi.fn(),
      clearSelection: vi.fn(),
      refresh: vi.fn(),
    })
    vi.mocked(useMoleculeAnalysis).mockReturnValue({
      activeTab: 'overview',
      setActiveTab: vi.fn(),
      selectedMolecules: [],
      analysisInput: [],
      sarSession: null,
      hasSelection: true,
    })
  })

  it('keeps results full width until a selected molecule is analyzed', () => {
    render(<MoleculeLibrary />)

    expect(screen.getByTestId('molecule-table')).toBeInTheDocument()
    expect(screen.queryByText('Selected 1 / 12')).not.toBeInTheDocument()
    expect(screen.queryByTestId('molecule-analysis-panel')).not.toBeInTheDocument()

    fireEvent.click(screen.getByText('Analyze selection'))
    expect(screen.getByTestId('molecule-analysis-panel')).toBeInTheDocument()

    fireEvent.click(screen.getByText('Close'))
    expect(screen.queryByTestId('molecule-analysis-panel')).not.toBeInTheDocument()
  })

  it('switches view mode from the page header', () => {
    render(<MoleculeLibrary />)

    fireEvent.click(screen.getByRole('button', { name: 'Card view' }))

    expect(setViewMode).toHaveBeenCalledWith('card')
  })
})
