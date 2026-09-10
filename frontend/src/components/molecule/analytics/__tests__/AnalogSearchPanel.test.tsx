import { describe, expect, it, vi, beforeEach } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'

vi.mock('react-i18next', () => ({
  initReactI18next: { type: '3rdParty', init: () => {} },
  useTranslation: () => ({ t: (key: string) => key }),
}))

vi.mock('@/hooks/useToast', () => ({ showToast: vi.fn() }))

vi.mock('@/api/http/molecule', () => ({
  molFindAnalogsWithActivity: vi.fn(),
}))

import { molFindAnalogsWithActivity } from '@/api/http/molecule'
import AnalogSearchPanel from '../AnalogSearchPanel'

const molecules = [{ mol_id: 'm1', esmiles: 'CCO', name: 'ethanol' }] as never[]

describe('AnalogSearchPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('does not search when no reference molecule is selected', () => {
    render(<AnalogSearchPanel molecules={molecules} />)
    fireEvent.click(screen.getByRole('button', { name: 'analytics.analogs.find' }))
    expect(molFindAnalogsWithActivity).not.toHaveBeenCalled()
  })

  it('submits the selected molecule id to the search', async () => {
    vi.mocked(molFindAnalogsWithActivity).mockResolvedValue([] as never)

    render(<AnalogSearchPanel molecules={molecules} />)

    fireEvent.change(screen.getByRole('combobox'), { target: { value: 'm1' } })
    fireEvent.click(screen.getByRole('button', { name: 'analytics.analogs.find' }))

    await waitFor(() =>
      expect(molFindAnalogsWithActivity).toHaveBeenCalledWith('m1', expect.any(Number)),
    )
  })
})
