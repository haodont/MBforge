// MoleculeTable usage test: row rendering + selection checkboxes + row click
// forwarding, plus the status/activity indicators derived from the record.
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

  it('renders molecule rows with selection and status/activity indicators', () => {
    const onRowClick = vi.fn()
    const view = render(<MoleculeTable {...defaultProps} onRowClick={onRowClick} />)

    expect(screen.getByText('A')).toBeInTheDocument()
    const checkboxes = screen.getAllByRole('checkbox')
    expect(checkboxes).toHaveLength(2)
    expect(screen.getByRole('checkbox', { name: 'Select A' })).toBeInTheDocument()

    fireEvent.click(screen.getByText('A'))
    expect(onRowClick).toHaveBeenCalledWith(mockMolecules[0])

    // Auto-detected records surface the translated status label with its hint.
    view.rerender(
      <MoleculeTable
        {...defaultProps}
        molecules={[{ ...mockMolecules[0], status: 'pending' }]}
      />,
    )
    expect(screen.getByText('mol.status.pending')).toHaveAttribute(
      'title',
      '模型自动识别结果，尚未人工修正',
    )

    // Records without activity are flagged as missing it.
    view.rerender(
      <MoleculeTable
        {...defaultProps}
        molecules={[{ ...mockMolecules[0], activity: null }]}
      />,
    )
    expect(screen.getByText('mol.activityMissing')).toBeInTheDocument()
  })
})
