import { describe, it, expect, vi, beforeEach } from 'vitest'
import { cleanup, render, screen, waitFor, act } from '@testing-library/react'

vi.mock('@/api/query/hooks', () => ({
  useIngestQueue: vi.fn(),
  useIngestStats: vi.fn(),
  useIngestLogs: vi.fn(),
  useWorkerStatus: vi.fn(),
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
    // No locale bundle is loaded, so the key is the rendered text. Params are
    // appended so assertions can still see interpolated values.
    t: (key: string, params?: Record<string, unknown>) => {
      if (!params) return key
      const rendered = Object.entries(params)
        .map(([k, v]) => `${k}=${String(v)}`)
        .join(' ')
      return `${key} ${rendered}`
    },
    i18n: { language: 'en' },
  }),
}))

import {
  useIngestQueue,
  useIngestStats,
  useIngestLogs,
  useWorkerStatus,
} from '@/api/query/hooks'
import ProcessingQueue from '../ProcessingQueue'

function mockQueue(tasks: { id: string; status: string; doc_id: string; run_id?: string }[]) {
  const now = Date.now()
  vi.mocked(useIngestQueue).mockReturnValue({
    data: tasks.map(t => ({
      id: t.id,
      run_id: t.run_id ?? t.id,
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
    vi.mocked(useIngestLogs).mockReturnValue({
      data: undefined,
    } as unknown as ReturnType<typeof useIngestLogs>)
  })

  it('walks the queue through loading, empty, populated and deduplicated states', () => {
    // Loading: the default queue/stats mocks have no data yet.
    render(<ProcessingQueue />)
    expect(screen.getByText('Loading...')).toBeInTheDocument()
    cleanup()

    mockQueue([])
    render(<ProcessingQueue />)
    // i18n returns key as-is.
    expect(screen.getByText('queue.emptyHint')).toBeInTheDocument()
    cleanup()

    mockQueue([
      { id: 't1', status: 'processing', doc_id: 'doc1' },
      { id: 't2', status: 'pending', doc_id: 'doc2' },
    ])
    render(<ProcessingQueue />)
    expect(screen.getByText('doc1.pdf')).toBeInTheDocument()
    expect(screen.getByText('doc2.pdf')).toBeInTheDocument()
    cleanup()

    // Several task rows for one document still render a single row.
    mockQueue([
      { id: 't1', status: 'processing', doc_id: 'doc1' },
      { id: 't2', status: 'done', doc_id: 'doc1' },
    ])
    render(<ProcessingQueue />)
    expect(screen.getAllByText('doc1.pdf')).toHaveLength(1)
  })

  it('fetches logs on demand through the query hook when a task row toggles logs', async () => {
    vi.mocked(useIngestLogs).mockReturnValue({
      data: [
        { doc_id: 'doc1', stage: 'moldet', level: 'info', message: 'hello', ts_ms: 1_000 },
      ],
      isLoading: false,
    } as unknown as ReturnType<typeof useIngestLogs>)
    mockQueue([
      { id: 't1', status: 'processing', doc_id: 'doc1' },
    ])
    render(<ProcessingQueue />)

    // Nothing is prefetched on mount; the toggle is what triggers the query.
    expect(useIngestLogs).not.toHaveBeenCalled()

    const toggle = screen.getByText('queue.showLogs')
    act(() => toggle.click())
    await waitFor(() => expect(useIngestLogs).toHaveBeenCalledWith('/tmp/lib', 'doc1'))
  })

  it('explains the pause and names the models still downloading until every model is ready', () => {
    mockQueue([{ id: 't1', status: 'pending', doc_id: 'doc1' }])
    vi.mocked(useWorkerStatus).mockReturnValue({
      data: {
        status: 'online',
        ts: Date.now(),
        model_gate: {
          ready: false,
          required: ['moldet', 'molparser'],
          missing: [
            { id: 'moldet', name: 'MolDetv2-FT', status: 'not_found', error: null },
            { id: 'molparser', name: 'MolParser-Mobile', status: 'partial', error: null },
          ],
          reason: 'missing models: moldet (not_found)',
        },
      },
    } as unknown as ReturnType<typeof useWorkerStatus>)

    render(<ProcessingQueue />)

    expect(screen.getByText('queue.modelsBlockedTitle')).toBeInTheDocument()
    expect(screen.getByText(/MolDetv2-FT, MolParser-Mobile/)).toBeInTheDocument()

    cleanup()

    vi.mocked(useWorkerStatus).mockReturnValue({
      data: {
        status: 'online',
        ts: Date.now(),
        model_gate: { ready: true, required: [], missing: [], reason: null },
      },
    } as unknown as ReturnType<typeof useWorkerStatus>)

    render(<ProcessingQueue />)

    expect(screen.queryByText('queue.modelsBlockedTitle')).not.toBeInTheDocument()
  })
})
