import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { PatentFactsArtifact } from '@/api/http/library'
import PatentAnalysisPane from './PatentAnalysisPane'

const reviewHooks = vi.hoisted(() => ({
  useReviewQueue: vi.fn(),
  mutateAsync: vi.fn(),
}))
vi.mock('@/api/query/hooks/useReview', () => ({
  useReviewQueue: reviewHooks.useReviewQueue,
  useReviewDecide: () => ({ mutateAsync: reviewHooks.mutateAsync, isPending: false }),
}))

const conflict = {
  conflict_id: 'conflict-1',
  slot_id: 'slot-1',
  kind: 'measurement' as const,
  doc_id: 'doc-1',
  page: 4,
  evidence_ids: ['evidence-rule', 'evidence-llm'],
  candidates: [
    { source: 'deterministic' as const, fields: { metric: 'IC50', comparator: '<', value_text: '10', unit: 'nM' }, signature: 'rule', evidence_ids: ['evidence-rule'] },
    { source: 'llm' as const, fields: { metric: 'IC50', comparator: '=', value_text: '20', unit: 'nM' }, signature: 'llm', evidence_ids: ['evidence-llm'] },
  ],
}

const facts: PatentFactsArtifact = {
  doc_id: 'doc-1',
  run_id: 'run-1',
  sections: [],
  entries: [],
  synthesis_steps: [],
  assay_methods: [],
  examples: [],
  measurements: [],
  issues: [{ code: 'llm_analysis_fallback', severity: 'warning', message: 'LLM unavailable' }],
  stats: {},
  analysis_status: 'fallback',
  extraction_mode: 'deterministic',
  conflicts: [conflict],
  review_candidates: [],
  llm: { error_code: 'sidecar_not_ready', error: 'raw provider details must not be shown' },
}

const reviewItem = {
  id: 'review-1',
  kind: 'patent_fact_review',
  doc_id: 'doc-1',
  page: 4,
  bbox: null,
  crop_relpath: null,
  smiles: null,
  name: 'IC50',
  confidence: null,
  reasons: [],
  context_text: null,
  status: 'pending',
  payload: { slot_id: 'slot-1', doc_id: 'doc-1', revision: 4, conflict },
  created_at: null,
  resolved_at: null,
}

describe('PatentAnalysisPane', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    reviewHooks.useReviewQueue.mockReturnValue({
      data: { items: [reviewItem], total: 1, page: 1, page_size: 100 },
      isPending: false,
      isError: false,
      refetch: vi.fn(),
    })
    reviewHooks.mutateAsync.mockResolvedValue({ updated: 1, skipped: 0, results: [] })
  })

  it('renders the fallback conflict, keeps assays and species separate and submits an explicit revisioned decision', async () => {
    const onOpenEvidence = vi.fn()
    render(<PatentAnalysisPane docId="doc-1" libraryRoot="/library" facts={facts} onOpenEvidence={onOpenEvidence} />)

    expect(screen.getByText(/Fell back to rule extraction/)).toBeInTheDocument()
    expect(screen.getByText(/LLM service is unavailable/)).toBeInTheDocument()
    expect(screen.getByText('< 10 nM')).toBeInTheDocument()
    expect(screen.getByText('= 20 nM')).toBeInTheDocument()
    expect(screen.getByText('Analysis revision 4')).toBeInTheDocument()
    expect(screen.queryByText('raw provider details must not be shown')).not.toBeInTheDocument()

    fireEvent.click(screen.getAllByRole('button', { name: 'Open source' })[1])
    expect(onOpenEvidence).toHaveBeenCalledWith('evidence-llm', 4)

    fireEvent.click(screen.getByRole('button', { name: 'Use LLM suggestion' }))
    await waitFor(() => expect(reviewHooks.mutateAsync).toHaveBeenCalledWith({
      libraryRoot: '/library',
      items: [{ kind: 'patent_fact_review', id: 'review-1', expected_revision: 4, choice: 'llm' }],
      action: 'confirm',
    }))

    // With no review conflicts left the reporting table owns the pane.
    cleanup()
    reviewHooks.useReviewQueue.mockReturnValue({ data: { items: [], total: 0 }, isPending: false, isError: false })
    const methods = ['human MRGPRX2 HEK293', 'mouse Mrgprb2 mast cells'].map((system, index) => ({
      assay_method_id: `assay-${index}`, doc_id: 'doc-1', target: index ? 'Mrgprb2' : 'MRGPRX2', system,
      endpoint: index ? 'degranulation' : 'calcium flux', assay_type: 'IC50', conditions: { species: index ? 'mouse' : 'human' },
      raw_text: system, section_id: '', page_start: index + 1, page_end: index + 1, evidence_ids: [`method-${index}`],
    }))
    const measurements = methods.map((method, index) => ({
      measurement_id: `measurement-${index}`, doc_id: 'doc-1', compound_entry_id: null, assay_method_id: method.assay_method_id,
      mol_id: 'mol-1', metric: 'IC50', linking_status: 'linked', evidence_ids: [`value-${index}`], provenance: {},
      value: { raw_text: index ? '> 2 µM' : '< 100 nM', operator: index ? '>' : '<', original_value: index ? 2 : 100,
        original_unit: index ? 'µM' : 'nM', canonical_value: null, canonical_unit: '', qualitative_value: '' },
    }))
    render(<PatentAnalysisPane docId="doc-1" libraryRoot="/library" facts={{ ...facts, measurements, assay_methods: methods }} onOpenEvidence={onOpenEvidence} />)

    const table = screen.getByRole('table')
    expect(within(table).getAllByRole('row')).toHaveLength(3)
    expect(within(table).getByText('human MRGPRX2 HEK293')).toBeInTheDocument()
    expect(within(table).getByText('mouse Mrgprb2 mast cells')).toBeInTheDocument()
    expect(within(table).getByText('< 100 nM')).toBeInTheDocument()
    expect(within(table).getByText('> 2 µM')).toBeInTheDocument()
    fireEvent.click(within(table).getAllByRole('button', { name: '2 sources' })[0])
    fireEvent.click(screen.getByRole('button', { name: /Source 2.*method-0/ }))
    expect(onOpenEvidence).toHaveBeenCalledWith('method-0')
  })
})
