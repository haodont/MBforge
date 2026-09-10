import { describe, expect, it, vi, beforeEach } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClientProvider } from '@tanstack/react-query'
import { createQueryClient } from '@/api/query/client'

vi.mock('react-i18next', () => ({
  initReactI18next: { type: '3rdParty', init: () => {} },
  useTranslation: () => ({ t: (key: string) => key }),
}))

vi.mock('@/hooks/useToast', () => ({ showToast: vi.fn() }))

vi.mock('@/api/http/readiness', () => ({
  readinessSummary: vi.fn(),
  readinessProbeLlm: vi.fn(),
  readinessDemoRun: vi.fn(),
}))

vi.mock('@/api/http/ingest_queue', () => ({
  ingestList: vi.fn(),
}))

import {
  readinessSummary,
  readinessProbeLlm,
  readinessDemoRun,
  type ReadinessSummary,
} from '@/api/http/readiness'
import ReadinessTab from '../ReadinessTab'

function makeSummary(overrides: Partial<ReadinessSummary> = {}): ReadinessSummary {
  return {
    library: {
      configured: true,
      path: 'C:/lib',
      exists: true,
      writable: true,
      error: null,
    },
    database: { ok: true, error: null },
    models: [
      {
        id: 'moldet',
        name: 'MolDet',
        status: 'ready',
        local_path: 'C:/cache/moldet.onnx',
        size_mb: 6.0,
        expected_size_mb: 6.0,
        cache_dir: 'C:/cache',
        last_error: null,
      },
      {
        id: 'molparser',
        name: 'MolParser',
        status: 'missing',
        local_path: null,
        size_mb: null,
        expected_size_mb: 20,
        cache_dir: 'C:/cache/hf',
        last_error: 'download interrupted',
      },
      {
        id: 'rdkit',
        name: 'RDKit',
        status: 'ready',
        local_path: 'builtin',
        size_mb: 0,
        expected_size_mb: 0,
        cache_dir: null,
        last_error: null,
      },
    ],
    llm: {
      configured: true,
      provider: 'openai',
      model: 'gpt-4o',
      base_url: 'https://api.openai.com/v1',
      has_api_key: true,
    },
    ocr: { chain: ['paddleocr'], error: null },
    ...overrides,
  }
}

describe('ReadinessTab', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  function renderTab(libraryRoot: string) {
    const client = createQueryClient()
    return render(
      <QueryClientProvider client={client}>
        <ReadinessTab libraryRoot={libraryRoot} />
      </QueryClientProvider>,
    )
  }

  it('renders a card per subsystem with status from the summary', async () => {
    vi.mocked(readinessSummary).mockResolvedValue(makeSummary())

    renderTab('C:/lib')

    await waitFor(() => screen.getByText('settings.readiness.library'))
    expect(screen.getByText('settings.readiness.database')).toBeTruthy()
    expect(screen.getByText('settings.readiness.ocr')).toBeTruthy()
    expect(screen.getByText('settings.readiness.llm')).toBeTruthy()
    // Model cards render per models[] entry, keyed by name.
    expect(screen.getByText('MolDet')).toBeTruthy()
    expect(screen.getByText('MolParser')).toBeTruthy()
    expect(screen.getByText('RDKit')).toBeTruthy()
    // Ready lamps for library / database / ready models / ocr / llm.
    expect(screen.getAllByText('settings.readiness.state.ready').length).toBeGreaterThanOrEqual(5)
    // Missing model shows error lamp, expected size (formatted MB), cache dir, last error.
    expect(screen.getByText('settings.readiness.state.error')).toBeTruthy()
    expect(screen.getByText('20 MB')).toBeTruthy()
    expect(screen.getByText('C:/cache/hf')).toBeTruthy()
    expect(screen.getByText('download interrupted')).toBeTruthy()
  })

  it('shows the General-tab hint when the library is not configured', async () => {
    vi.mocked(readinessSummary).mockResolvedValue(
      makeSummary({
        library: { configured: false, path: null, exists: false, writable: false, error: null },
      }),
    )

    renderTab('')

    await waitFor(() => screen.getByText('settings.readiness.libraryHint'))
    expect(screen.getAllByText('settings.readiness.state.attention').length).toBeGreaterThanOrEqual(1)
  })

  it('re-fetches the summary when the re-check button is clicked', async () => {
    vi.mocked(readinessSummary).mockResolvedValue(makeSummary())

    renderTab('C:/lib')
    await waitFor(() => screen.getByText('settings.readiness.library'))
    expect(readinessSummary).toHaveBeenCalledTimes(1)

    fireEvent.click(screen.getByRole('button', { name: 'settings.readiness.refresh' }))
    await waitFor(() => expect(readinessSummary).toHaveBeenCalledTimes(2))
  })

  it('shows latency after a successful LLM probe', async () => {
    vi.mocked(readinessSummary).mockResolvedValue(makeSummary())
    vi.mocked(readinessProbeLlm).mockResolvedValue({
      ok: true,
      latency_ms: 123,
      error: null,
      provider: 'openai',
      model: 'gpt-4o',
    })

    renderTab('C:/lib')
    await waitFor(() => screen.getByText('settings.readiness.library'))

    fireEvent.click(screen.getByRole('button', { name: 'settings.readiness.probeLlm' }))
    await waitFor(() => screen.getByText('settings.readiness.probeOk'))
  })

  it('shows the error after a failed LLM probe', async () => {
    vi.mocked(readinessSummary).mockResolvedValue(makeSummary())
    vi.mocked(readinessProbeLlm).mockResolvedValue({
      ok: false,
      latency_ms: null,
      error: 'connection refused',
      provider: 'openai',
      model: 'gpt-4o',
    })

    renderTab('C:/lib')
    await waitFor(() => screen.getByText('settings.readiness.library'))

    fireEvent.click(screen.getByRole('button', { name: 'settings.readiness.probeLlm' }))
    await waitFor(() => screen.getByText('settings.readiness.probeFailed'))
  })

  it('shows the demo-run error when the library is not configured', async () => {
    vi.mocked(readinessSummary).mockResolvedValue(
      makeSummary({
        library: { configured: false, path: null, exists: false, writable: false, error: null },
      }),
    )
    vi.mocked(readinessDemoRun).mockResolvedValue({
      ok: false,
      task_id: null,
      file_path: '',
      error: 'library not configured',
    })

    renderTab('')
    await waitFor(() => screen.getByText('settings.readiness.library'))

    fireEvent.click(screen.getByRole('button', { name: 'settings.readiness.demoRun' }))
    await waitFor(() => screen.getByText('settings.readiness.demoFailed'))
    expect(readinessDemoRun).toHaveBeenCalledTimes(1)
  })
})
