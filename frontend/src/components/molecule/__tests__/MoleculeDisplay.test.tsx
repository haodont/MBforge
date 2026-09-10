import { render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import MoleculeDisplay from '../MoleculeDisplay'

const { renderLocalStructure, setImgError } = vi.hoisted(() => ({
  renderLocalStructure: vi.fn(),
  setImgError: vi.fn(),
}))

vi.mock('@/api/http/molecule', () => ({
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

  it('renders the local RDKit image without requesting a public image', async () => {
    render(<MoleculeDisplay smiles="CCO" />)

    await waitFor(() => {
      expect(renderLocalStructure).toHaveBeenCalledWith('CCO', 240, 240)
    })
    await waitFor(() => {
      expect(screen.getByRole('img', { name: 'CCO' }).getAttribute('src')).toContain('data:image/svg+xml')
    })
  })

  it('uses the source crop with a correction warning when local rendering fails', async () => {
    renderLocalStructure.mockRejectedValueOnce(new Error('RDKit unavailable'))
    render(<MoleculeDisplay smiles="CCO" sourceImageUrl="/source-crop.png" />)

    await waitFor(() => {
      expect(screen.getByRole('img', { name: 'CCO' })).toHaveAttribute('src', '/source-crop.png')
    })
    expect(screen.getByText('原始图片 · 待人工矫正')).toBeInTheDocument()
  })
})
