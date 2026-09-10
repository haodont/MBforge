import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, act } from '@testing-library/react'

vi.mock('@/api/query/hooks', () => ({
  useIngestQueue: vi.fn(),
  useIngestStats: vi.fn(),
  useWorkerStatus: vi.fn(),
  useCancelTask: vi.fn(),
  useRetryTask: vi.fn(),
  useDeleteTask: vi.fn(),
  useCancelBatch: vi.fn(),
  useRetryBatch: vi.fn(),
  useCleanupTasks: vi.fn(),
  useSetTaskPriority: vi.fn(),
}))

vi.mock('@/api/query/useIngestSSE', () => ({
  useIngestSSE: vi.fn(),
}))

vi.mock('@/context/AppContext', () => ({
  useAppContext: vi.fn().mockReturnValue({ libraryRoot: '/tmp/lib' }),
}))

vi.mock('react-i18next', () => ({
  initReactI18next: { type: '3rdParty', init: () => {} },
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { language: 'en' },
  }),
}))

vi.mock('@/api/http/ingest_queue', async () => {
  const actual = await vi.importActual<typeof import('@/api/http/ingest_queue')>('@/api/http/ingest_queue')
  return {
    ...actual,
    ingestGetLogs: vi.fn().mockResolvedValue([]),
  }
})

import {
  useIngestQueue,
  useIngestStats,
  useWorkerStatus,
  useCancelTask,
  useRetryTask,
  useDeleteTask,
  useCancelBatch,
  useRetryBatch,
  useCleanupTasks,
  useSetTaskPriority,
} from '@/api/query/hooks'
import { ingestGetLogs } from '@/api/http/ingest_queue'
import ProcessingQueue from '../ProcessingQueue'

function mockMutationHooks() {
  vi.mocked(useCancelTask).mockReturnValue({ mutateAsync: vi.fn(), isPending: false } as unknown as ReturnType<typeof useCancelTask>)
  vi.mocked(useRetryTask).mockReturnValue({ mutateAsync: vi.fn(), isPending: false } as unknown as ReturnType<typeof useRetryTask>)
  vi.mocked(useDeleteTask).mockReturnValue({ mutateAsync: vi.fn(), isPending: false } as unknown as ReturnType<typeof useDeleteTask>)
  vi.mocked(useCancelBatch).mockReturnValue({ mutateAsync: vi.fn(), isPending: false } as unknown as ReturnType<typeof useCancelBatch>)
  vi.mocked(useRetryBatch).mockReturnValue({ mutateAsync: vi.fn(), isPending: false } as unknown as ReturnType<typeof useRetryBatch>)
  vi.mocked(useCleanupTasks).mockReturnValue({ mutateAsync: vi.fn(), isPending: false } as unknown as ReturnType<typeof useCleanupTasks>)
  vi.mocked(useSetTaskPriority).mockReturnValue({ mutateAsync: vi.fn(), isPending: false } as unknown as ReturnType<typeof useSetTaskPriority>)
}

function mockQueue(tasks: { id: string; status: string; doc_id: string }[]) {
  const now = Date.now()
  vi.mocked(useIngestQueue).mockReturnValue({
    data: tasks.map(t => ({
      id: t.id,
      doc_id: t.doc_id,
      file_path: `${t.doc_id}.pdf`,
      status: t.status,
      stage: '',
      retry_count: 0,
      error: null,
      file_size_bytes: null,
      started_at: null,
      created_at: Math.floor(now / 1000) - 100,
      updated_at: Math.floor(now / 1000) - 50,
      priority: 0,
      stage_statuses: {},
    })),
    isLoading: false,
    isError: false,
    error: null,
  } as unknown as ReturnType<typeof useIngestQueue>)

  vi.mocked(useIngestStats).mockReturnValue({
    data: { total: tasks.length, pending: 0, processing: 0, done: 0, failed: 0, cancelled: 0, avg_stage_durations_ms: [] },
    isLoading: false,
  } as unknown as ReturnType<typeof useIngestStats>)

  vi.mocked(useWorkerStatus).mockReturnValue({
    data: { status: 'online', ts: now },
  } as unknown as ReturnType<typeof useWorkerStatus>)
}

describe('ProcessingQueue', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockMutationHooks()
    vi.mocked(useIngestQueue).mockReturnValue({
      data: [],
      isLoading: true,
      isError: false,
    } as unknown as ReturnType<typeof useIngestQueue>)
    vi.mocked(useIngestStats).mockReturnValue({
      data: null,
      isLoading: true,
    } as unknown as ReturnType<typeof useIngestStats>)
    vi.mocked(useWorkerStatus).mockReturnValue({
      data: undefined,
    } as unknown as ReturnType<typeof useWorkerStatus>)
  })

  it('shows loading state', () => {
    render(<ProcessingQueue />)
    expect(screen.getByText('Loading...')).toBeInTheDocument()
  })

  it('shows empty state when queue is empty', () => {
    mockQueue([])
    render(<ProcessingQueue />)
    // i18n returns key as-is.
    expect(screen.getByText('queue.emptyHint')).toBeInTheDocument()
  })

  it('renders tasks when present', () => {
    mockQueue([
      { id: 't1', status: 'processing', doc_id: 'doc1' },
      { id: 't2', status: 'pending', doc_id: 'doc2' },
    ])
    render(<ProcessingQueue />)
    expect(screen.getByText('doc1.pdf')).toBeInTheDocument()
    expect(screen.getByText('doc2.pdf')).toBeInTheDocument()
  })

  it('renders only one task row for duplicate doc ids', () => {
    mockQueue([
      { id: 't1', status: 'processing', doc_id: 'doc1' },
      { id: 't2', status: 'done', doc_id: 'doc1' },
    ])
    render(<ProcessingQueue />)
    expect(screen.getAllByText('doc1.pdf')).toHaveLength(1)
  })

  it('does not prefetch logs on mount', () => {
    mockQueue([
      { id: 't1', status: 'processing', doc_id: 'doc1' },
      { id: 't2', status: 'pending', doc_id: 'doc2' },
    ])
    render(<ProcessingQueue />)
    expect(ingestGetLogs).not.toHaveBeenCalled()
  })

  it('fetches logs on demand when a task row toggles logs', async () => {
    const mockGetLogs = vi.mocked(ingestGetLogs)
    mockGetLogs.mockResolvedValue([
      { doc_id: 'doc1', stage: 'moldet', level: 'info', message: 'hello', ts_ms: 1_000 },
    ])
    mockQueue([
      { id: 't1', status: 'processing', doc_id: 'doc1' },
    ])
    render(<ProcessingQueue />)
    const toggle = screen.getByText('queue.showLogs')
    act(() => toggle.click())
    await waitFor(() => expect(mockGetLogs).toHaveBeenCalledWith('/tmp/lib', 'doc1', 200))
  })
})
