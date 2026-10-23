import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import ResearchShelf from './ResearchShelf'

const state = vi.hoisted(() => ({
  openTab: vi.fn(),
  refetchFacts: vi.fn(),
  useDocuments: vi.fn(),
  useIngestQueue: vi.fn(),
  usePatentAnalysis: vi.fn(),
  useDocumentPatentFacts: vi.fn(),
}))

vi.mock('react-i18next', () => ({
  initReactI18next: { type: '3rdParty', init: () => {} },
  useTranslation: () => ({
    t: (key: string, values?: Record<string, unknown>) => Object.entries(values ?? {})
      .reduce((text, [name, value]) => text.replace('{{' + name + '}}', String(value)), key),
  }),
}))
vi.mock('react-router-dom', () => ({ useNavigate: () => vi.fn() }))
vi.mock('@/api/query/hooks', () => ({
  useDocuments: state.useDocuments,
  useIngestQueue: state.useIngestQueue,
  usePatentAnalysis: state.usePatentAnalysis,
  useDocumentPatentFacts: state.useDocumentPatentFacts,
}))
vi.mock('@/context/AppContext', () => ({
  useAppContext: () => ({
    libraryRoot: '/library',
    openTab: state.openTab,
    researchDocumentIds: [],
    setResearchDocumentIds: vi.fn(),
  }),
}))

const document = { doc_id: 'doc-1', file_name: 'patent.pdf', title: 'Patent A', page_count: 8 }
const task = {
  id: 'task-1', run_id: 'run-1', file_path: 'patent.pdf', doc_id: 'doc-1', status: 'done',
  stage: 'patent', retry_count: 0, error: null, file_size_bytes: null, started_at: 1,
  created_at: 1, updated_at: 2, priority: 0, stage_statuses: {},
}
const facts = {
  doc_id: 'doc-1', run_id: 'run-1', sections: [], entries: [], synthesis_steps: [],
  assay_methods: [], examples: [], measurements: [], issues: [], stats: {},
  analysis_status: 'succeeded', extraction_mode: 'hybrid', review_candidates: [{ review_item_id: 'review-1' }],
}

describe('ResearchShelf', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    state.useDocuments.mockReturnValue({ data: { documents: [document] }, isPending: false, isError: false })
    state.useIngestQueue.mockReturnValue({ data: [task], isPending: false, isError: false })
    state.usePatentAnalysis.mockReturnValue({ mutateAsync: vi.fn(), isPending: false })
    state.useDocumentPatentFacts.mockReturnValue({
      data: { ok: true, data: facts },
      refetch: state.refetchFacts,
    })
  })

  it('shows analysis details only for the task run and opens that document from its task card', () => {
    const { unmount } = render(<ResearchShelf />)

    expect(screen.getByText('patentAnalysis.status.succeeded')).toBeInTheDocument()
    expect(screen.getByText('patentAnalysis.mode.hybrid')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'research.task.openResult' }))
    expect(state.openTab).toHaveBeenCalledWith({
      type: 'pdf',
      title: 'Patent A',
      libraryRoot: '/library',
      initialSidePaneTab: 'analysis',
      doc: { doc_id: 'doc-1', path: 'patent.pdf', doc_type: 'pdf', title: 'Patent A' },
    })

    unmount()
    state.useDocumentPatentFacts.mockReturnValue({
      data: { ok: true, data: { ...facts, run_id: 'older-run' } },
      refetch: state.refetchFacts,
    })
    render(<ResearchShelf />)
    expect(screen.getAllByText('research.task.noCurrentArtifact')).toHaveLength(1)
    expect(screen.queryByText('patentAnalysis.status.succeeded')).not.toBeInTheDocument()
  })
})
