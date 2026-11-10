/**
 * Project status widgets (src/components/project):
 * StatPill, WorkerStatusBadge, IngestLogPanel, TaskRow.
 *
 * One test per component contract: stat rendering, status-label mapping,
 * log rows / empty state, and the TaskRow identity + status display.
 */
import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { StatPill } from '../StatPill'
import { WorkerStatusBadge } from '../WorkerStatusBadge'
import IngestLogPanel from '../IngestLogPanel'
import { TaskRow } from '../TaskRow'
import type { IngestLogEvent, IngestTask } from '@/api/http/ingest_queue'

vi.mock('react-i18next', () => ({
  initReactI18next: { type: '3rdParty', init: () => {} },
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { language: 'en' },
  }),
}))

describe('StatPill', () => {
  it('renders label/value and the optional icon', () => {
    render(<StatPill label="Total" value={42} tone="neutral" icon={<span data-testid="icon">●</span>} />)
    expect(screen.getByText('Total')).toBeInTheDocument()
    expect(screen.getByText('42')).toBeInTheDocument()
    expect(screen.getByTestId('icon')).toBeInTheDocument()
  })
})

describe('WorkerStatusBadge', () => {
  it('maps every worker status to its translated label', () => {
    const cases = [
      ['online', 'queue.workerOnline'],
      ['offline', 'queue.workerOffline'],
      ['unknown', 'queue.workerUnknown'],
    ] as const
    for (const [status, label] of cases) {
      const { unmount } = render(<WorkerStatusBadge status={status} />)
      expect(screen.getByText(label), status).toBeInTheDocument()
      unmount()
    }
  })
})

describe('IngestLogPanel', () => {
  it('renders log rows and the empty state', () => {
    const logs: IngestLogEvent[] = [
      { doc_id: 'd1', stage: 'inspector', level: 'info', message: '开始解析', ts_ms: 1718500000000 },
      { doc_id: 'd1', stage: 'ocr', level: 'warn', message: '第3页置信度低', ts_ms: 1718500001000 },
    ]
    const filled = render(<IngestLogPanel logs={logs} />)
    expect(screen.getByText('开始解析')).toBeInTheDocument()
    expect(screen.getByText('第3页置信度低')).toBeInTheDocument()
    filled.unmount()

    render(<IngestLogPanel logs={[]} />)
    expect(screen.getByText(/暂无日志/)).toBeInTheDocument()
  })
})

describe('TaskRow', () => {
  const now = Date.now()

  function makeTask(overrides: Partial<IngestTask> = {}): IngestTask {
    const nowSec = Math.floor(now / 1000)
    return {
      id: 't1',
      run_id: 'r1',
      doc_id: 'doc-1',
      file_path: '/tmp/test.pdf',
      status: 'pending',
      stage: '',
      retry_count: 0,
      error: null,
      file_size_bytes: 102400,
      started_at: null,
      created_at: nowSec - 100,
      updated_at: nowSec - 50,
      priority: 0,
      stage_statuses: {},
      ...overrides,
    }
  }

  it('renders task identity, status and error details', () => {
    const baseProps = {
      now,
      isLogsExpanded: false,
      logs: [] as IngestLogEvent[],
      onToggleLogs: vi.fn(),
    }

    const failed = render(<TaskRow {...baseProps} task={makeTask({ status: 'failed', error: 'OCR timeout' })} />)
    expect(screen.getByText('test.pdf')).toBeInTheDocument()
    expect(screen.getByText('queue.failed')).toBeInTheDocument()
    fireEvent.click(screen.getByText('queue.showDetails'))
    expect(screen.getByText('OCR timeout')).toBeInTheDocument()
    failed.unmount()

    const done = render(<TaskRow {...baseProps} task={makeTask({ status: 'done' })} />)
    expect(screen.getByText('queue.done')).toBeInTheDocument()
    done.unmount()

    render(<TaskRow {...baseProps} task={makeTask({ status: 'processing' })} />)
    expect(screen.getByText('queue.processing')).toBeInTheDocument()
  })
})
