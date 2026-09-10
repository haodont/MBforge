import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import MoleculeTable from '../MoleculeTable'

vi.mock('react-i18next', () => ({
  initReactI18next: { type: '3rdParty', init: () => {} },
  useTranslation: () => ({ t: (key: string) => key }),
}))

const mockMolecules = [
  {
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
  },
]

const defaultProps = {
  molecules: mockMolecules,
  loading: false,
  selectedIds: new Set<string>(),
  sort: { field: 'name' as const, direction: 'asc' as const },
  onSort: vi.fn(),
  onToggleSelect: vi.fn(),
  onSelectRange: vi.fn(),
  onRowClick: vi.fn(),
  lastClickedId: null,
  setLastClickedId: vi.fn(),
}

describe('MoleculeTable', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders molecule name', () => {
    render(<MoleculeTable {...defaultProps} />)
    expect(screen.getByText('A')).toBeInTheDocument()
  })

  it('calls onRowClick when row clicked', () => {
    const onRowClick = vi.fn()
    render(<MoleculeTable {...defaultProps} onRowClick={onRowClick} />)
    fireEvent.click(screen.getByText('A'))
    expect(onRowClick).toHaveBeenCalledWith(mockMolecules[0])
  })

  it('renders row and header checkboxes', () => {
    render(<MoleculeTable {...defaultProps} />)
    const checkboxes = screen.getAllByRole('checkbox')
    expect(checkboxes).toHaveLength(2)
    expect(screen.getByRole('checkbox', { name: 'Select A' })).toBeInTheDocument()
  })

  it('uses the translated label for auto-detected records', () => {
    render(
      <MoleculeTable
        {...defaultProps}
        molecules={[{ ...mockMolecules[0], status: 'pending' }]}
      />,
    )

    expect(screen.getByText('mol.status.pending')).toHaveAttribute(
      'title',
      '模型自动识别结果，尚未人工修正',
    )
  })

  it('marks a record with no activity as needing activity data', () => {
    render(
      <MoleculeTable
        {...defaultProps}
        molecules={[{ ...mockMolecules[0], activity: null }]}
      />,
    )

    expect(screen.getByText('mol.activityMissing')).toHaveClass('activity-missing-badge')
  })
})
