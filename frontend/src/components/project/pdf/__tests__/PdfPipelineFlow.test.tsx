import { describe, expect, it, vi } from 'vitest'
import { render } from '@testing-library/react'
import PdfPipelineFlow from '../PdfPipelineFlow'
import type { IngestTask } from '@/api/http/ingest_queue'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}))

function makeTask(overrides: Partial<IngestTask> = {}): IngestTask {
  return {
    id: 'task-1',
    run_id: 'run-1',
    file_path: 'document.pdf',
    doc_id: 'doc-1',
    status: 'processing',
    stage: 'unknown',
    retry_count: 0,
    error: null,
    file_size_bytes: null,
    started_at: null,
    created_at: 1,
    updated_at: 1,
    priority: 0,
    stage_statuses: {},
    ...overrides,
  }
}

describe('PdfPipelineFlow', () => {
  it('uses checkpoint stage statuses instead of the queue stage index', () => {
    render(
      <PdfPipelineFlow
        variant="full"
        task={makeTask({
          stage: 'unknown',
          stage_statuses: {
            extract: 'success',
            detection: 'success',
            markdown: 'running',
          },
        })}
      />,
    )

    const activeLabels = document.querySelectorAll('.pdf-pipeline-step-label.is-active')

    expect(activeLabels).toHaveLength(1)
    expect(activeLabels[0]).toHaveTextContent('pdfPipeline.stage.markdown')
  })
})
