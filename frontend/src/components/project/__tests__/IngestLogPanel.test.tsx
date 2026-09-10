import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import IngestLogPanel from '../IngestLogPanel'
import type { IngestLogEvent } from '../../../api/http/ingest_queue'

const logs: IngestLogEvent[] = [
  { doc_id: 'd1', stage: 'inspector', level: 'info', message: '开始解析', ts_ms: 1718500000000 },
  { doc_id: 'd1', stage: 'ocr', level: 'warn', message: '第3页置信度低', ts_ms: 1718500001000 },
]

describe('IngestLogPanel', () => {
  it('renders log rows', () => {
    render(<IngestLogPanel logs={logs} />)
    expect(screen.getByText('开始解析')).toBeInTheDocument()
    expect(screen.getByText('第3页置信度低')).toBeInTheDocument()
  })

  it('shows empty state when no logs', () => {
    render(<IngestLogPanel logs={[]} />)
    expect(screen.getByText(/暂无日志/)).toBeInTheDocument()
  })
})
