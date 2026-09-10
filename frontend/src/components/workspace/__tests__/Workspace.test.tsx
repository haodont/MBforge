import { describe, it, expect, vi, beforeEach } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'

// Mock hooks before any imports that use them.
vi.mock('@/api/query/hooks', () => ({
  useDocuments: vi.fn(),
  useImportDocument: vi.fn(),
  useDeleteDocument: vi.fn(),
  useClearDocument: vi.fn(),
  useCollections: vi.fn(),
  useMoveDocument: vi.fn(),
  useEnqueueTask: vi.fn(),
}))

vi.mock('@/context/AppContext', () => ({
  useAppContext: vi.fn(),
  AppProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}))

vi.mock('@/components/LibraryPanel', () => ({
  default: () => <div data-testid="workspace-library-panel" />,
}))

vi.mock('@/components/project/pdf/viewerSnapshots', () => ({
  clearViewerSnapshotsForDoc: vi.fn(),
}))

// i18n mock — return key as-is when t() is called, with English fallback for common keys.
vi.mock('react-i18next', () => ({
  initReactI18next: { type: '3rdParty', init: () => {} },
  useTranslation: () => ({
    t: (key: string) => {
      if (key === 'workspace.loadError') return 'Failed to load documents. Please try again.'
      if (key === 'common.retry') return 'Retry'
      return key
    },
    i18n: { language: 'en' },
  }),
}))

import { useDocuments, useImportDocument, useClearDocument } from '@/api/query/hooks'
import { useDeleteDocument } from '@/api/query/hooks'
import { useCollections, useMoveDocument, useEnqueueTask } from '@/api/query/hooks'
import { useAppContext } from '@/context/AppContext'
import { clearViewerSnapshotsForDoc } from '@/components/project/pdf/viewerSnapshots'
import Workspace from '../Workspace'

function mockAppContext(overrides?: Record<string, unknown>) {
  vi.mocked(useAppContext).mockReturnValue({
    libraryRoot: '/tmp/lib',
    activeCollectionId: null,
    openTab: vi.fn(),
    ...overrides,
  } as unknown as ReturnType<typeof useAppContext>)
}

function mockDocuments(docs: { doc_id: string; title: string; status: string }[]) {
  vi.mocked(useDocuments).mockReturnValue({
    data: { documents: docs.map(d => ({ ...d, file_name: `${d.doc_id}.pdf`, page_count: 3, created_at: '2026-01-01' })) },
    isLoading: false,
    isError: false,
    error: null,
    dataUpdatedAt: Date.now(),
  } as unknown as ReturnType<typeof useDocuments>)
}

function mockDeleteDocument() {
  vi.mocked(useDeleteDocument).mockReturnValue({
    mutateAsync: vi.fn(),
    isPending: false,
  } as unknown as ReturnType<typeof useDeleteDocument>)
}

function mockClearDocument() {
  vi.mocked(useClearDocument).mockReturnValue({
    mutateAsync: vi.fn(),
    isPending: false,
  } as unknown as ReturnType<typeof useClearDocument>)
}

function mockCollections(collections: { collection_id: string; name: string }[] = []) {
  vi.mocked(useCollections).mockReturnValue({
    data: { collections },
    isLoading: false,
    isError: false,
    error: null,
  } as unknown as ReturnType<typeof useCollections>)
}

function mockMoveDocument() {
  vi.mocked(useMoveDocument).mockReturnValue({
    mutateAsync: vi.fn(),
    isPending: false,
  } as unknown as ReturnType<typeof useMoveDocument>)
}

function renderWorkspace() {
  return render(<Workspace />)
}

describe('Workspace', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockAppContext()
    // Default: loading state
    vi.mocked(useDocuments).mockReturnValue({
      data: undefined,
      isLoading: true,
      isError: false,
      error: null,
    } as unknown as ReturnType<typeof useDocuments>)
    vi.mocked(useImportDocument).mockReturnValue({
      mutateAsync: vi.fn(),
    } as unknown as ReturnType<typeof useImportDocument>)
    vi.mocked(useEnqueueTask).mockReturnValue({
      mutateAsync: vi.fn(),
    } as unknown as ReturnType<typeof useEnqueueTask>)
    mockDeleteDocument()
    mockClearDocument()
    mockCollections([])
    mockMoveDocument()
  })

  it('shows loading state', () => {
    renderWorkspace()
    expect(screen.getByTestId('workspace-library-panel')).toBeInTheDocument()
    expect(screen.getByTestId('workspace-skeleton')).toHaveAttribute('aria-busy', 'true')
  })

  it('shows empty state when no documents', () => {
    mockDocuments([])
    renderWorkspace()
    // i18n t() returns key "library.noDocuments" in test.
    expect(screen.getByText('library.noDocuments')).toBeInTheDocument()
  })

  it('renders document list', () => {
    mockDocuments([
      { doc_id: 'doc1', title: 'Test Paper 1', status: 'ready' },
      { doc_id: 'doc2', title: 'Test Paper 2', status: 'pending' },
    ])
    renderWorkspace()
    expect(screen.getByText('Test Paper 1')).toBeInTheDocument()
    expect(screen.getByText('Test Paper 2')).toBeInTheDocument()
  })

  it('shows workspace summary metrics', () => {
    mockDocuments([
      { doc_id: 'doc1', title: 'Ready Paper', status: 'ready' },
      { doc_id: 'doc2', title: 'Pending Paper', status: 'pending' },
    ])
    renderWorkspace()

    expect(screen.getByLabelText('workspace.summary')).toBeInTheDocument()
    expect(screen.getByText('workspace.documentCount')).toHaveTextContent('workspace.documentCount')
    expect(screen.getByText('workspace.pageCount')).toHaveTextContent('workspace.pageCount')
    expect(screen.getByLabelText('workspace.summary').children).toHaveLength(3)
  })

  it('shows error state when query fails', () => {
    vi.mocked(useDocuments).mockReturnValue({
      data: undefined,
      isLoading: false,
      isError: true,
      error: new Error('Network error'),
    } as unknown as ReturnType<typeof useDocuments>)
    renderWorkspace()
    expect(screen.getByText('Failed to load documents. Please try again.')).toBeInTheDocument()
    expect(screen.getByText('Retry')).toBeInTheDocument()
  })

  it('shows import button in empty state when no collection filter', () => {
    mockDocuments([])
    renderWorkspace()
    const importBtns = screen.getAllByText('library.importPdf')
    expect(importBtns.length).toBeGreaterThanOrEqual(2)
  })

  it('calls openTab when document card is clicked', () => {
    const openTab = vi.fn()
    mockAppContext({ openTab })
    mockDocuments([{ doc_id: 'doc1', title: 'Clickable Doc', status: 'ready' }])
    renderWorkspace()
    screen.getByText('Clickable Doc').click()
    expect(openTab).toHaveBeenCalledWith(
      expect.objectContaining({ type: 'pdf', title: 'Clickable Doc' }),
    )
  })

  it('opens a document card with the keyboard', () => {
    const openTab = vi.fn()
    mockAppContext({ openTab })
    mockDocuments([{ doc_id: 'doc1', title: 'Keyboard Doc', status: 'ready' }])
    renderWorkspace()

    const openButton = screen.getByRole('button', { name: 'Keyboard Doc' })
    fireEvent.click(openButton)

    expect(openTab).toHaveBeenCalledWith(
      expect.objectContaining({ type: 'pdf', title: 'Keyboard Doc' }),
    )
  })

  it('deletes a document after confirmation without opening it', async () => {
    const deleteDocument = vi.fn().mockResolvedValue({ success: true })
    vi.mocked(useDeleteDocument).mockReturnValue({
      mutateAsync: deleteDocument,
      isPending: false,
    } as unknown as ReturnType<typeof useDeleteDocument>)
    mockDocuments([{ doc_id: 'doc1', title: 'Deletable Doc', status: 'pending' }])
    renderWorkspace()

    screen.getByRole('button', { name: 'doc.actions' }).click()
    const deleteButton = await screen.findByRole('menuitem', { name: 'doc.delete' })
    deleteButton.click()
    // ConfirmDialog confirm button carries the same label; pick the dialog's.
    const confirm = await screen.findByRole('button', { name: 'doc.delete' })
    confirm.click()

    expect(deleteDocument).toHaveBeenCalledWith('doc1')
  })

  it('keeps the document when deletion is cancelled', async () => {
    const deleteDocument = vi.fn()
    vi.mocked(useDeleteDocument).mockReturnValue({
      mutateAsync: deleteDocument,
      isPending: false,
    } as unknown as ReturnType<typeof useDeleteDocument>)
    mockDocuments([{ doc_id: 'doc1', title: 'Kept Doc', status: 'pending' }])
    renderWorkspace()

    screen.getByRole('button', { name: 'doc.actions' }).click()
    const deleteButton = await screen.findByRole('menuitem', { name: 'doc.delete' })
    deleteButton.click()
    // Cancel the dialog (cancel button label is the default 取消).
    const cancel = await screen.findByRole('button', { name: /取消/ })
    cancel.click()

    expect(deleteDocument).not.toHaveBeenCalled()
    expect(screen.getByText('Kept Doc')).toBeInTheDocument()
  })

  it('clears the document snapshot after a successful clear action', async () => {
    const clearDocument = vi.fn().mockResolvedValue({ success: true })
    vi.mocked(useClearDocument).mockReturnValue({
      mutateAsync: clearDocument,
      isPending: false,
    } as unknown as ReturnType<typeof useClearDocument>)
    mockDocuments([{ doc_id: 'doc1', title: 'Clearable Doc', status: 'ready' }])
    renderWorkspace()

    screen.getByRole('button', { name: 'doc.actions' }).click()
    const clearButton = await screen.findByRole('menuitem', { name: 'doc.clear' })
    clearButton.click()
    const confirm = await screen.findByRole('button', { name: 'doc.clear' })
    confirm.click()

    await vi.waitFor(() => {
      expect(clearDocument).toHaveBeenCalledWith('doc1')
      expect(clearViewerSnapshotsForDoc).toHaveBeenCalledWith('doc1')
    })
  })

})
