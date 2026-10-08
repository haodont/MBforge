import { describe, expect, it, vi, beforeEach } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClientProvider } from '@tanstack/react-query'
import { createQueryClient } from '@/api/query/client'

vi.mock('react-i18next', () => ({
  initReactI18next: { type: '3rdParty', init: () => {} },
  useTranslation: () => ({ t: (key: string) => key }),
}))

vi.mock('@/hooks/useToast', () => ({ showToast: vi.fn() }))

vi.mock('@/api/http/molecule_chem', () => ({
  molGetStats: vi.fn(),
  molFindByMolecule: vi.fn(),
  molAddRelation: vi.fn(),
  molDeleteRelation: vi.fn(),
}))

import { molAddRelation } from '@/api/http/molecule_chem'
import RelationPanel from '../RelationPanel'

const molecules = [
  { mol_id: 'm1', esmiles: 'CCO', name: 'ethanol' },
  { mol_id: 'm2', esmiles: 'CCN', name: 'ethylamine' },
] as never[]

function renderPanel() {
  const client = createQueryClient()
  return render(
    <QueryClientProvider client={client}>
      <RelationPanel molecules={molecules} />
    </QueryClientProvider>,
  )
}

describe('RelationPanel destructive confirmation', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('does not add a relation when the dialog is cancelled', () => {
    renderPanel()
    fireEvent.click(screen.getByRole('button', { name: 'common.add' }))
    fireEvent.click(screen.getByRole('button', { name: /取消/ }))
    expect(molAddRelation).not.toHaveBeenCalled()
  })

  it('adds a relation only after confirming the dialog', async () => {
    vi.mocked(molAddRelation).mockResolvedValue({ id: 1 } as never)

    renderPanel()

    const selects = screen.getAllByRole('combobox')
    fireEvent.change(selects[0], { target: { value: 'm1' } })
    fireEvent.change(selects[1], { target: { value: 'm2' } })
    fireEvent.click(screen.getByRole('button', { name: 'common.add' }))
    // The dialog confirm shares the label; click the last match (in the modal).
    const confirmButtons = screen.getAllByRole('button', { name: 'common.add' })
    fireEvent.click(confirmButtons[confirmButtons.length - 1])

    await waitFor(() =>
      expect(molAddRelation).toHaveBeenCalledWith('m1', 'm2', 'similar', undefined),
    )
  })
})
