import { render, screen, waitFor } from '@testing-library/react'
import { QueryClientProvider } from '@tanstack/react-query'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { createQueryClient } from '@/api/query/client'
import MoleculeDisplay from '../MoleculeDisplay'

const { renderLocalStructure, setImgError } = vi.hoisted(() => ({
  renderLocalStructure: vi.fn(),
  setImgError: vi.fn(),
}))

vi.mock('@/api/http/molecule_chem', () => ({
  smilesToRdkitSvg: renderLocalStructure,
}))

vi.mock('@/hooks/useMoleculeDisplay', () => ({
  useMoleculeDisplay: () => ({
    imgError: false,
    setImgError,
    isEditing: false,
    draftSmiles: 'CCO',
    backendIssue: null,
    backendLoading: false,
    effectiveError: null,
    formula: null,
    mw: null,
    handleStartEdit: vi.fn(),
    handleApplyEdit: vi.fn(),
    handleCancelEdit: vi.fn(),
    handleKeyDown: vi.fn(),
    setDraftSmiles: vi.fn(),
  }),
}))

describe('MoleculeDisplay', () => {
  beforeEach(() => {
    renderLocalStructure.mockReset()
    renderLocalStructure.mockResolvedValue('<svg><rect width="10" height="10" /></svg>')
  })

  function renderDisplay(ui: React.ReactElement) {
    const client = createQueryClient()
    return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>)
  }

  it('renders the local RDKit image without requesting a public image', async () => {
    renderDisplay(<MoleculeDisplay smiles="CCO" />)

    await waitFor(() => {
      expect(renderLocalStructure).toHaveBeenCalledWith('CCO', 240, 240)
    })
    await waitFor(() => {
      expect(screen.getByRole('img', { name: 'CCO' }).getAttribute('src')).toContain('data:image/svg+xml')
    })
  })

  it('uses the source crop with a correction warning when local rendering fails', async () => {
    renderLocalStructure.mockRejectedValueOnce(new Error('RDKit unavailable'))
    renderDisplay(<MoleculeDisplay smiles="CCO" sourceImageUrl="/source-crop.png" />)

    await waitFor(() => {
      expect(screen.getByRole('img', { name: 'CCO' })).toHaveAttribute('src', '/source-crop.png')
    })
    expect(screen.getByText('原始图片 · 待人工矫正')).toBeInTheDocument()
  })
})
