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
  molFindAnalogsWithActivity: vi.fn(),
}))

import { molFindAnalogsWithActivity } from '@/api/http/molecule_chem'
import AnalogSearchPanel from '../AnalogSearchPanel'

const molecules = [{ mol_id: 'm1', esmiles: 'CCO', name: 'ethanol' }] as never[]

function renderPanel() {
  const client = createQueryClient()
  return render(
    <QueryClientProvider client={client}>
      <AnalogSearchPanel molecules={molecules} />
    </QueryClientProvider>,
  )
}

describe('AnalogSearchPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('does not search when no reference molecule is selected', () => {
    renderPanel()
    fireEvent.click(screen.getByRole('button', { name: 'analytics.analogs.find' }))
    expect(molFindAnalogsWithActivity).not.toHaveBeenCalled()
  })

  it('submits the selected molecule id to the search', async () => {
    vi.mocked(molFindAnalogsWithActivity).mockResolvedValue([] as never)

    renderPanel()

    fireEvent.change(screen.getByRole('combobox'), { target: { value: 'm1' } })
    fireEvent.click(screen.getByRole('button', { name: 'analytics.analogs.find' }))

    await waitFor(() =>
      expect(molFindAnalogsWithActivity).toHaveBeenCalledWith('m1', expect.any(Number)),
    )
  })
})
