import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('react-i18next', () => ({
  initReactI18next: { type: '3rdParty', init: () => {} },
  useTranslation: () => ({
    t: (key: string, fallback?: string) => fallback ?? key,
  }),
}))

const sitesData = [
  {
    site_id: 'site-1',
    scaffold_id: 'sc-1',
    site_label: 'R1',
    atom_map_num: 1,
    attachment_count: 1,
    bond_type: null,
    source_text: '',
    status: 'confirmed' as const,
    properties: {},
    created_at: null,
    updated_at: null,
    options: [
      {
        option_id: 'opt-1',
        site_id: 'site-1',
        fragment_id: 'frag-1',
        normalized_smiles: 'F',
        definition_text: 'F',
        constraints: {},
        status: 'confirmed' as const,
        created_at: null,
        updated_at: null,
      },
      {
        option_id: 'opt-2',
        site_id: 'site-1',
        fragment_id: null,
        normalized_smiles: null,
        definition_text: 'unknown',
        constraints: {},
        status: 'pending' as const,
        created_at: null,
        updated_at: null,
      },
    ],
  },
]

vi.mock('@/api/query/useMarkush', () => ({
  useMarkushSites: () => ({ isLoading: false, isError: false, data: sitesData }),
  useMarkushEnumerationPreview: () => ({
    isPending: false,
    isSuccess: false,
    isError: false,
    error: null,
    data: null,
    mutate: vi.fn(),
  }),
  useMarkushEnumerationRun: () => ({
    isPending: false,
    isSuccess: false,
    isError: false,
    error: null,
    data: null,
    mutate: vi.fn(),
  }),
  useMarkushEnumerationResults: () => ({
    isSuccess: false,
    isError: false,
    error: null,
    data: [],
  }),
  useMarkushGeneratedDecide: () => ({
    isPending: false,
    mutate: vi.fn(),
  }),
}))

import EnumerationPanel from '../EnumerationPanel'

describe('EnumerationPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders sites and confirmed fragment options, disabling unconfirmed options', () => {
    render(<EnumerationPanel libraryRoot="/tmp/lib" scaffoldId="sc-1" />)
    expect(screen.getByText('Markush 结构枚举')).toBeInTheDocument()
    const optionInputs = screen.getAllByRole('checkbox')
    // Two options: frag-1 enabled, pending option without fragment_id disabled
    expect(optionInputs).toHaveLength(2)
    expect(optionInputs[0]).toBeEnabled()
    expect(optionInputs[1]).toBeDisabled()
  })

  it('disables preview and run until a fragment is selected', () => {
    render(<EnumerationPanel libraryRoot="/tmp/lib" scaffoldId="sc-1" />)
    const previewBtn = screen.getByRole('button', { name: /预览组合数/ })
    const runBtn = screen.getByRole('button', { name: /执行枚举/ })
    expect(previewBtn).toBeDisabled()
    expect(runBtn).toBeDisabled()
  })

  it('enables preview after selecting a confirmed fragment', () => {
    render(<EnumerationPanel libraryRoot="/tmp/lib" scaffoldId="sc-1" />)
    const optionInputs = screen.getAllByRole('checkbox')
    fireEvent.click(optionInputs[0])
    const previewBtn = screen.getByRole('button', { name: /预览组合数/ })
    expect(previewBtn).toBeEnabled()
  })
})
