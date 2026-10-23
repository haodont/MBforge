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
  openTab: vi.fn(),
}))
vi.mock('@/api/http/review', () => api)
vi.mock('@/api/http/molecule_chem', () => ({ smilesToRdkitSvg: vi.fn().mockResolvedValue('<svg />') }))
vi.mock('@/context/AppContext', () => ({
  useAppContext: () => ({ libraryRoot: '/library', openTab: api.openTab }),
}))

import ReviewCenter from './ReviewCenter'

const item = {
  id: 'r-1', kind: 'low_conf_molecule', doc_id: 'doc-1', page: 2,
  bbox: [1, 2, 3, 4], crop_relpath: null, smiles: 'CCO', name: 'ethanol',
  confidence: 0.4, reasons: ['low confidence'], context_text: 'context',
  status: 'pending', payload: {}, created_at: null, resolved_at: null,
}

const patentFactItem = {
  id: 'patent-review-1', kind: 'patent_fact_review', doc_id: 'doc-1', page: 4,
  bbox: null, crop_relpath: null, smiles: null, name: 'IC50', confidence: null,
  reasons: [], context_text: null, status: 'pending',
  payload: {
    slot_id: 'slot-1', doc_id: 'doc-1', revision: 7,
    conflict: {
      conflict_id: 'conflict-1', slot_id: 'slot-1', kind: 'measurement', doc_id: 'doc-1',
      page: 4, evidence_ids: ['ev-rule', 'ev-llm'],
      candidates: [
        { source: 'deterministic', fields: { metric: 'IC50', comparator: '<', value_text: '10', unit: 'nM' }, signature: 'rule', evidence_ids: ['ev-rule'] },
        { source: 'llm', fields: { metric: 'IC50', comparator: '=', value_text: '20', unit: 'nM' }, signature: 'llm', evidence_ids: ['ev-llm'] },
      ],
    },
  },
  created_at: null, resolved_at: null,
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

  it('renders filtered queue details and applies bulk and keyboard decisions', async () => {
    renderCenter()
    expect(await screen.findByRole('heading', { name: 'ethanol' })).toBeInTheDocument()
    expect(screen.getAllByText('CCO').length).toBeGreaterThan(0)

    fireEvent.click(screen.getByRole('checkbox', { name: 'review.selectItem' }))
    fireEvent.click(screen.getAllByRole('button', { name: /review.confirm/ })[0])

    await waitFor(() => expect(api.reviewDecide).toHaveBeenCalledWith('/library', [{ kind: 'low_conf_molecule', id: 'r-1' }], 'confirm', ''))

    // The same decision must also be reachable from the c / x shortcuts.
    api.reviewDecide.mockClear()
    fireEvent.keyDown(window, { key: 'c' })
    await waitFor(() => expect(api.reviewDecide).toHaveBeenCalledWith('/library', [{ kind: 'low_conf_molecule', id: 'r-1' }], 'confirm', ''))
    fireEvent.keyDown(window, { key: 'x' })
    await waitFor(() => expect(api.reviewDecide).toHaveBeenCalledWith('/library', [{ kind: 'low_conf_molecule', id: 'r-1' }], 'reject', ''))
  })

  it('requires an explicit patent value and submits its expected revision', async () => {
    api.reviewQueue.mockResolvedValue({ items: [patentFactItem], total: 1, page: 1, page_size: 25 })
    renderCenter()
    expect(await screen.findByRole('heading', { name: 'IC50' })).toBeInTheDocument()

    fireEvent.click(screen.getByRole('checkbox', { name: 'review.selectItem' }))
    expect(screen.getByRole('button', { name: 'review.confirm' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'review.reject' })).toBeDisabled()
    expect(screen.getByText('review.patentFact.revision')).toBeInTheDocument()

    fireEvent.click(screen.getAllByRole('button', { name: 'review.openSource' })[1])
    expect(api.openTab).toHaveBeenCalledWith({
      type: 'document',
      title: 'doc-1',
      libraryRoot: '/library',
      doc: { doc_id: 'doc-1', title: 'doc-1', path: 'storage/doc-1/source.pdf', doc_type: 'pdf', added_at: '', hash: '' },
      initialPage: 4,
      initialBbox: undefined,
      initialEvidenceId: 'ev-llm',
    })

    fireEvent.click(screen.getByRole('button', { name: 'review.patentFact.choose.llm' }))
    await waitFor(() => expect(api.reviewDecide).toHaveBeenCalledWith('/library', [{
      kind: 'patent_fact_review',
      id: 'patent-review-1',
      choice: 'llm',
      expected_revision: 7,
    }], 'confirm', ''))
  })

  it('clears the whole review center only after the confirmation dialog is confirmed', async () => {
    renderCenter()
    await screen.findByRole('heading', { name: 'ethanol' })

    // Header trigger opens the ConfirmDialog; cancelling must not clear anything.
    fireEvent.click(screen.getByRole('button', { name: /review.clearAll/ }))
    fireEvent.click(screen.getByRole('button', { name: /取消/ }))
    expect(api.reviewClear).not.toHaveBeenCalled()

    // The dialog confirm button shares the label; pick the last one rendered.
    const dialogButtons = screen.getAllByRole('button', { name: /review.clearAll/ })
    fireEvent.click(dialogButtons[dialogButtons.length - 1])

    await waitFor(() => expect(api.reviewClear).toHaveBeenCalledWith('/library'))
  })
})
