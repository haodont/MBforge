import { describe, expect, it, vi, beforeEach } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'

vi.mock('react-i18next', () => ({
  initReactI18next: { type: '3rdParty', init: () => {} },
  useTranslation: () => ({ t: (key: string) => key }),
}))

vi.mock('@/hooks/useToast', () => ({ showToast: vi.fn() }))

vi.mock('@/api/http/molecule', () => ({
  molSearchSubstructure: vi.fn(),
}))

import { molSearchSubstructure } from '@/api/http/molecule'
import SubstructureSearchPanel from '../SubstructureSearchPanel'

describe('SubstructureSearchPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('does not search when the query is blank', () => {
    render(<SubstructureSearchPanel />)
    fireEvent.click(screen.getByRole('button', { name: 'common.search' }))
    expect(molSearchSubstructure).not.toHaveBeenCalled()
  })

  it('submits the trimmed query to the search', async () => {
    vi.mocked(molSearchSubstructure).mockResolvedValue([] as never)

    render(<SubstructureSearchPanel />)
    const input = screen.getByPlaceholderText('analytics.substructure.placeholder')
    fireEvent.change(input, { target: { value: '  c1ccccc1  ' } })
    fireEvent.click(screen.getByRole('button', { name: 'common.search' }))

    await waitFor(() =>
      expect(molSearchSubstructure).toHaveBeenCalledWith('c1ccccc1', expect.any(Number)),
    )
  })
})
