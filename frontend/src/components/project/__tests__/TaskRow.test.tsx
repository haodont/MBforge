import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { TaskRow } from '../TaskRow'
import type { IngestTask } from '@/api/http/ingest_queue'

vi.mock('react-i18next', () => ({
  initReactI18next: { type: '3rdParty', init: () => {} },
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { language: 'en' },
  }),
}))

function makeTask(overrides: Partial<IngestTask> = {}): IngestTask {
  const now = Math.floor(Date.now() / 1000)
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
    created_at: now - 100,
    updated_at: now - 50,
    priority: 0,
    stage_statuses: {},
    ...overrides,
  }
}

describe('TaskRow', () => {
  it('renders file name', () => {
    render(
      <TaskRow
        task={makeTask()}
        now={Date.now()}
        isLogsExpanded={false}
        logs={[]}
        isActioning={false}
        onToggleLogs={vi.fn()}
        onCancel={vi.fn()}
        onRetry={vi.fn()}
        onDelete={vi.fn()}
        onTogglePin={vi.fn()}
      />,
    )
    expect(screen.getByText('test.pdf')).toBeInTheDocument()
  })

  it('shows error message for failed tasks', () => {
    render(
      <TaskRow
        task={makeTask({ status: 'failed', error: 'OCR timeout' })}
        now={Date.now()}
        isLogsExpanded={false}
        logs={[]}
        isActioning={false}
        onToggleLogs={vi.fn()}
        onCancel={vi.fn()}
        onRetry={vi.fn()}
        onDelete={vi.fn()}
        onTogglePin={vi.fn()}
      />,
    )
    fireEvent.click(screen.getByText('queue.showDetails'))
    expect(screen.getByText('OCR timeout')).toBeInTheDocument()
  })

  it('shows retry button for failed tasks', () => {
    render(
      <TaskRow
        task={makeTask({ status: 'failed' })}
        now={Date.now()}
        isLogsExpanded={false}
        logs={[]}
        isActioning={false}
        onToggleLogs={vi.fn()}
        onRetry={vi.fn()}
        onCancel={vi.fn()}
        onDelete={vi.fn()}
        onTogglePin={vi.fn()}
      />,
    )
    expect(screen.getAllByText('queue.retryTask').length).toBeGreaterThanOrEqual(1)
  })

  it('passes the selected resume stage from the retry menu', () => {
    const onRetry = vi.fn()
    render(
      <TaskRow
        task={makeTask({ status: 'done' })}
        now={Date.now()}
        isLogsExpanded={false}
        logs={[]}
        isActioning={false}
        onToggleLogs={vi.fn()}
        onCancel={vi.fn()}
        onRetry={onRetry}
        onDelete={vi.fn()}
        onTogglePin={vi.fn()}
      />,
    )
    fireEvent.click(screen.getByText('queue.retryTask'))
    fireEvent.click(screen.getByText('queue.retryFromMarkdown'))
    expect(onRetry).toHaveBeenCalledWith(expect.objectContaining({ id: 't1' }), 'markdown')
  })

  it('calls onCancel when cancel button clicked', () => {
    const onCancel = vi.fn()
    render(
      <TaskRow
        task={makeTask({ status: 'processing' })}
        now={Date.now()}
        isLogsExpanded={false}
        logs={[]}
        isActioning={false}
        onToggleLogs={vi.fn()}
        onCancel={onCancel}
        onRetry={vi.fn()}
        onDelete={vi.fn()}
        onTogglePin={vi.fn()}
      />,
    )
    fireEvent.click(screen.getByText('queue.cancelTask'))
    expect(onCancel).toHaveBeenCalledOnce()
  })

  it('calls onTogglePin for pending pinnable tasks', () => {
    const onTogglePin = vi.fn()
    render(
      <TaskRow
        task={makeTask({ status: 'pending', priority: 0 })}
        now={Date.now()}
        isLogsExpanded={false}
        logs={[]}
        isActioning={false}
        onToggleLogs={vi.fn()}
        onCancel={vi.fn()}
        onRetry={vi.fn()}
        onDelete={vi.fn()}
        onTogglePin={onTogglePin}
      />,
    )
    fireEvent.click(screen.getByText('queue.pinTask'))
    expect(onTogglePin).toHaveBeenCalledOnce()
  })
})
