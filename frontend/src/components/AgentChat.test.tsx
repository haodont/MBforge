// AgentChat context-reference contract: the selected molecule/task references
// are sent with the question, an analysis request flips allowAnalysis, and a
// reopened history session replays its stored task/artifact references without
// re-issuing the analysis request.
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import AgentChat from './AgentChat'
import type * as ResearchHttp from '@/api/http/research'
import type { AgentChatEvent } from '@/api/http/agent'

const state = vi.hoisted(() => ({
  useDocuments: vi.fn(),
  useSettings: vi.fn(),
  useIngestQueue: vi.fn(),
  useMoleculePage: vi.fn(),
  useMolecule: vi.fn(),
  useDocumentPatentFacts: vi.fn(),
  useAppContext: vi.fn(),
  openTab: vi.fn(),
  saved: null as ResearchHttp.ResearchSession | null,
  createResearch: vi.fn<(title: string) => Promise<ResearchHttp.ResearchSession>>(),
  loadResearch: vi.fn<(id: string) => Promise<ResearchHttp.ResearchSession>>(),
  importResearch: vi.fn<(items: ResearchHttp.ResearchSession[]) => Promise<void>>(),
  deleteResearch: vi.fn<(id: string) => Promise<void>>(),
  useResearchSessions: vi.fn(),
  streamResearchChat: vi.fn<(root: string, session: ResearchHttp.ResearchSession, requestId: string, message: string, allowAnalysis: boolean,
    onEvent: (event: AgentChatEvent) => void, signal: AbortSignal) => Promise<void>>(),
}))

vi.mock('react-i18next', () => ({
  initReactI18next: { type: '3rdParty', init: () => {} },
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { language: 'en', exists: () => false },
  }),
}))
vi.mock('react-router-dom', () => ({ useNavigate: () => vi.fn() }))
vi.mock('@/api/query/hooks', () => ({
  useDocuments: state.useDocuments,
  useSettings: state.useSettings,
  useIngestQueue: state.useIngestQueue,
  useDocumentPatentFacts: state.useDocumentPatentFacts,
}))
vi.mock('@/api/query/hooks/useMolecules', () => ({ useMoleculePage: state.useMoleculePage, useMolecule: state.useMolecule }))
vi.mock('./molecule/MoleculeDetailDrawer', () => ({
  default: ({ molecule, onClose }: { molecule: { mol_id: string }; onClose: () => void }) => (
    <section role="dialog" aria-label="Molecule details"><p>{molecule.mol_id}</p><button onClick={onClose}>Close molecule</button></section>
  ),
}))
vi.mock('@/api/http/research', async importOriginal => ({ ...await importOriginal<typeof ResearchHttp>(), streamResearchChat: state.streamResearchChat }))
vi.mock('@/api/query/hooks/useResearch', () => ({
  useResearchSessions: state.useResearchSessions,
  useResearchSession: () => ({ data: undefined, isError: false }),
  useCreateResearchSession: () => ({ mutateAsync: state.createResearch }),
  useLoadResearchSession: () => ({ mutateAsync: state.loadResearch }),
  useImportResearchHistory: () => ({ mutateAsync: state.importResearch }),
  useDeleteResearchSession: () => ({ mutateAsync: state.deleteResearch, isPending: false }),
}))
vi.mock('@/context/AppContext', () => ({ useAppContext: state.useAppContext }))

const document = { doc_id: 'doc-1', title: 'Patent A', file_name: 'patent.pdf', page_count: 3 }
const molecule = { mol_id: 'mol-1', name: 'Ligand A' }
const task = { id: 'task-1', run_id: 'run-1', doc_id: 'doc-1', file_path: 'patent.pdf', status: 'done', stage: 'patent', updated_at: 2 }
const sameRunTask = { ...task, id: 'task-2', stage: 'markdown', updated_at: 3 }
const facts = {
  doc_id: 'doc-1', run_id: 'run-1', revision: 1, sections: [], entries: [], synthesis_steps: [],
  assay_methods: [], examples: [], measurements: [], issues: [], stats: {},
  analysis_status: 'succeeded', extraction_mode: 'hybrid', review_candidates: [],
}

describe('AgentChat context references', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    localStorage.clear()
    state.saved = { id: 'server-session', title: 'Server research', updatedAt: 2, messages: [] }
    state.createResearch.mockImplementation(() => Promise.resolve(state.saved as ResearchHttp.ResearchSession))
    state.loadResearch.mockImplementation(() => Promise.resolve(state.saved as ResearchHttp.ResearchSession))
    state.importResearch.mockResolvedValue(undefined)
    state.deleteResearch.mockResolvedValue(undefined)
    state.useResearchSessions.mockReturnValue({ data: [{ id: 'server-session', title: 'Server research', updatedAt: 2 }], isSuccess: true, isPending: false, isError: false, refetch: vi.fn() })
    state.useDocuments.mockReturnValue({ data: { documents: [document] }, isPending: false, isError: false })
    state.useSettings.mockReturnValue({ data: { success: true, settings: { llm: { provider: 'ollama', model: 'test' } } }, isError: false })
    state.useIngestQueue.mockReturnValue({ data: [task, sameRunTask], isPending: false, isError: false, refetch: vi.fn() })
    state.useMoleculePage.mockReturnValue({ data: { items: [molecule] }, isPending: false, isError: false })
    state.useMolecule.mockReturnValue({ data: molecule, isPending: false, isError: false, refetch: vi.fn() })
    state.useDocumentPatentFacts.mockReturnValue({ data: { ok: true, data: facts }, isPending: false, isError: false, refetch: vi.fn() })
    state.useAppContext.mockReturnValue({
      libraryRoot: '/library', researchDocumentIds: [], setResearchDocumentIds: vi.fn(), openTab: state.openTab,
    })
    state.streamResearchChat.mockImplementation((_root, session, requestId, message, _allowAnalysis, onEvent) => {
      state.saved = { ...session, messages: [...session.messages,
        { id: 'user', request_id: requestId, role: 'user', content: message },
        { id: 'reply', request_id: requestId, role: 'assistant', content: 'Answer', status: 'complete' }] }
      onEvent({ type: 'done', data: { text: 'Answer' } })
      return Promise.resolve()
    })
  })

  it('sends the selected references with the question and replays stored references from history', async () => {
    // --- Selecting molecule and task references sends them with the question ---
    const first = render(<AgentChat />)
    fireEvent.click(screen.getByRole('button', { name: 'research.context' }))
    fireEvent.click(screen.getByRole('tab', { name: /research\.contextMolecules/ }))
    fireEvent.click(screen.getByRole('button', { name: 'Ligand A · mol-1' }))
    fireEvent.click(screen.getByRole('tab', { name: /research\.contextTasks/ }))
    fireEvent.click(screen.getByRole('button', { name: 'Patent A · pdfPipeline.stage.patent · research.task.done · run-1' }))
    fireEvent.click(screen.getByRole('button', { name: 'Patent A · pdfPipeline.stage.markdown · research.task.done · run-1' }))
    fireEvent.click(screen.getByRole('button', { name: 'research.doneSelecting' }))
    fireEvent.click(screen.getAllByRole('button', { name: '展开' })[0])
    expect(screen.getByText('patentAnalysis.status.succeeded')).toBeInTheDocument()
    fireEvent.click(screen.getAllByRole('button', { name: 'research.task.openResult' })[0])
    expect(state.openTab).toHaveBeenCalledWith(expect.objectContaining({
      initialSidePaneTab: 'analysis',
      doc: expect.objectContaining({ doc_id: 'doc-1' }),
    }))
    fireEvent.click(screen.getByRole('button', { name: 'Ligand A' }))
    expect(await screen.findByRole('dialog', { name: 'Molecule details' })).toHaveTextContent('mol-1')
    expect(state.useMolecule).toHaveBeenLastCalledWith('/library', 'mol-1')
    fireEvent.click(screen.getByRole('button', { name: 'Close molecule' }))
    expect(screen.getByRole('button', { name: 'Ligand A' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'research.removeMolecule' }))
    expect(screen.queryByRole('button', { name: 'Ligand A' })).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /research\.context/ }))
    fireEvent.click(screen.getByRole('tab', { name: /research\.contextMolecules/ }))
    fireEvent.click(screen.getByRole('button', { name: 'Ligand A · mol-1' }))
    fireEvent.click(screen.getByRole('button', { name: 'research.doneSelecting' }))

    fireEvent.change(screen.getByRole('textbox', { name: 'research.placeholder' }), { target: { value: 'Explain this run' } })
    fireEvent.click(screen.getByRole('button', { name: 'agent.send' }))

    await waitFor(() => expect(state.streamResearchChat).toHaveBeenCalledOnce())
    const [root, request, , question, allowAnalysis] = state.streamResearchChat.mock.calls[0]
    expect(root).toBe('/library')
    expect(question).toBe('Explain this run')
    expect(allowAnalysis).toBe(false)
    expect(request.moleculeRefs).toEqual([{ mol_id: 'mol-1', name: 'Ligand A' }])
    expect(request.taskRefs).toEqual([
      { task_id: 'task-1', run_id: 'run-1', doc_id: 'doc-1', stage: 'patent', status: 'done' },
      { task_id: 'task-2', run_id: 'run-1', doc_id: 'doc-1', stage: 'markdown', status: 'done' },
    ])

    // --- Reopening a stored session replays its references without re-asking ---
    first.unmount()
    localStorage.clear()
    state.openTab.mockClear()
    state.streamResearchChat.mockClear()
    state.useAppContext.mockReturnValue({ libraryRoot: '/library', researchDocumentIds: ['doc-1'], setResearchDocumentIds: vi.fn(), openTab: state.openTab })
    state.streamResearchChat.mockImplementation((_root, session, requestId, message, _allowAnalysis, onEvent) => {
      const reference = { task_id: 'task-1', run_id: 'run-1', doc_id: 'doc-1' }
      const artifact = { doc_id: 'doc-1', run_id: 'run-1', revision: 1 }
      state.saved = { ...session, title: 'Server research', messages: [
        { id: 'user', role: 'user', content: message, request_id: requestId },
        { id: 'reply', role: 'assistant', content: 'Answer', status: 'complete', request_id: requestId, taskRefs: [reference], artifactRefs: [artifact] },
      ] }
      onEvent({ type: 'task', data: { reference } })
      onEvent({ type: 'artifact', data: { reference: artifact } })
      onEvent({ type: 'done', data: { text: 'Answer' } })
      return Promise.resolve()
    })

    render(<AgentChat />)
    fireEvent.click(screen.getByRole('button', { name: 'research.askAnalyze' }))
    expect(await screen.findByText('Answer')).toBeInTheDocument()
    expect(state.streamResearchChat.mock.calls[0][4]).toBe(true)
    expect(screen.getByRole('button', { name: 'research.openArtifact' })).toBeInTheDocument()
    await waitFor(() => expect(screen.getByRole('button', { name: 'research.new' })).toBeEnabled())
    fireEvent.click(screen.getByRole('button', { name: 'research.new' }))
    fireEvent.click(screen.getByRole('button', { name: 'research.history' }))
    fireEvent.click(screen.getByRole('button', { name: /Server research/ }))
    expect(await screen.findByText('Answer')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'research.openArtifact' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '展开' }))
    fireEvent.click(screen.getByRole('button', { name: 'research.task.openResult' }))
    expect(state.openTab).toHaveBeenCalledWith(expect.objectContaining({ initialSidePaneTab: 'analysis' }))
    expect(state.streamResearchChat).toHaveBeenCalledOnce()
  })
})
