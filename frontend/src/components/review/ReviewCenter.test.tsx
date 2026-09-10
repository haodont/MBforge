import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { QueryClientProvider } from '@tanstack/react-query'
import { createQueryClient } from '@/api/query/client'

vi.mock('react-i18next', () => ({
  initReactI18next: { type: '3rdParty', init: () => {} },
  useTranslation: () => ({ t: (key: string, values?: Record<string, unknown>) => Object.entries(values ?? {}).reduce((text, [name, value]) => text.replace(`{{${name}}}`, String(value)), key) }),
}))

const api = vi.hoisted(() => ({
  reviewQueue: vi.fn(),
  reviewStats: vi.fn(),
  reviewHistory: vi.fn(),
  reviewDecide: vi.fn(),
  reviewClear: vi.fn(),
}))
vi.mock('@/api/http/review', () => api)
vi.mock('@/api/http/molecule', () => ({ smilesToRdkitSvg: vi.fn().mockResolvedValue('<svg />') }))
vi.mock('@/context/AppContext', () => ({
  useAppContext: () => ({ libraryRoot: '/library', openTab: vi.fn() }),
}))

import ReviewCenter from './ReviewCenter'

const item = {
  id: 'r-1', kind: 'low_conf_molecule', doc_id: 'doc-1', page: 2,
  bbox: [1, 2, 3, 4], crop_relpath: null, smiles: 'CCO', name: 'ethanol',
  confidence: 0.4, reasons: ['low confidence'], context_text: 'context',
  status: 'pending', payload: {}, created_at: null, resolved_at: null,
}

describe('ReviewCenter', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    api.reviewQueue.mockResolvedValue({ items: [item], total: 1, page: 1, page_size: 25 })
    api.reviewStats.mockResolvedValue({ items: [], pending: 1 })
    api.reviewHistory.mockResolvedValue({ entity_type: 'review_item', entity_id: 'r-1', history: [] })
    api.reviewDecide.mockResolvedValue({ updated: 1, skipped: 0, results: [] })
    api.reviewClear.mockResolvedValue({ deleted_items: 1, deleted_candidates: 0 })
  })

  function renderCenter() {
    const client = createQueryClient()
    return render(
      <QueryClientProvider client={client}>
        <ReviewCenter />
      </QueryClientProvider>,
    )
  }

  it('renders filtered queue details and applies a bulk decision', async () => {
    renderCenter()
    expect(await screen.findByRole('heading', { name: 'ethanol' })).toBeInTheDocument()
    expect(screen.getAllByText('CCO').length).toBeGreaterThan(0)

    fireEvent.click(screen.getByRole('checkbox', { name: 'review.selectItem' }))
    fireEvent.click(screen.getAllByRole('button', { name: /review.confirm/ })[0])

    await waitFor(() => expect(api.reviewDecide).toHaveBeenCalledWith('/library', [{ kind: 'low_conf_molecule', id: 'r-1' }], 'confirm', ''))
  })

  it('supports c and x shortcuts for the focused item', async () => {
    renderCenter()
    await screen.findByRole('heading', { name: 'ethanol' })
    fireEvent.keyDown(window, { key: 'c' })
    await waitFor(() => expect(api.reviewDecide).toHaveBeenCalledWith('/library', [{ kind: 'low_conf_molecule', id: 'r-1' }], 'confirm', ''))
    fireEvent.keyDown(window, { key: 'x' })
    await waitFor(() => expect(api.reviewDecide).toHaveBeenCalledWith('/library', [{ kind: 'low_conf_molecule', id: 'r-1' }], 'reject', ''))
  })

  it('clears the whole review center after confirming the dialog', async () => {
    renderCenter()
    await screen.findByRole('heading', { name: 'ethanol' })

    // Header trigger opens the ConfirmDialog.
    fireEvent.click(screen.getByRole('button', { name: /review.clearAll/ }))
    // The dialog confirm button shares the label; pick the last one rendered.
    const dialogButtons = screen.getAllByRole('button', { name: /review.clearAll/ })
    fireEvent.click(dialogButtons[dialogButtons.length - 1])

    await waitFor(() => expect(api.reviewClear).toHaveBeenCalledWith('/library'))
  })

  it('does not clear when the confirmation dialog is cancelled', async () => {
    renderCenter()
    await screen.findByRole('heading', { name: 'ethanol' })

    fireEvent.click(screen.getByRole('button', { name: /review.clearAll/ }))
    fireEvent.click(screen.getByRole('button', { name: /取消/ }))

    expect(api.reviewClear).not.toHaveBeenCalled()
  })
})
