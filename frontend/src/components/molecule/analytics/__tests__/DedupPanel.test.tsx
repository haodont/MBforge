import { describe, expect, it, vi, beforeEach } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'

vi.mock('react-i18next', () => ({
  initReactI18next: { type: '3rdParty', init: () => {} },
  useTranslation: () => ({ t: (key: string) => key }),
}))

vi.mock('@/hooks/useToast', () => ({ showToast: vi.fn() }))
vi.mock('@/api/http/molecule', () => ({ molDedupBatch: vi.fn() }))

import { molDedupBatch } from '@/api/http/molecule'
import DedupPanel from '../DedupPanel'

const molecules = [{ mol_id: 'm1', esmiles: 'CCO', name: 'ethanol' }] as never[]

describe('DedupPanel destructive confirmation', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('does not write when the dialog is cancelled', () => {
    render(<DedupPanel molecules={molecules} onComplete={vi.fn()} />)
    fireEvent.click(screen.getByRole('button', { name: 'analytics.dedup.run' }))
    fireEvent.click(screen.getByRole('button', { name: /取消/ }))
    expect(molDedupBatch).not.toHaveBeenCalled()
  })

  it('writes only after confirming the dialog', () => {
    vi.mocked(molDedupBatch).mockResolvedValue({ duplicates: [], new_mols: [], relations_added: 0 })
    render(<DedupPanel molecules={molecules} onComplete={vi.fn()} />)
    fireEvent.click(screen.getByRole('button', { name: 'analytics.dedup.run' }))
    // The dialog confirm shares the label; click the last match (in the modal).
    const confirmButtons = screen.getAllByRole('button', { name: 'analytics.dedup.run' })
    fireEvent.click(confirmButtons[confirmButtons.length - 1])
    expect(molDedupBatch).toHaveBeenCalledWith([['m1', 'CCO']], 0.95)
  })
})
