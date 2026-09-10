import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('../_utils', () => ({
  apiUrl: vi.fn(),
  httpGet: vi.fn(),
  httpPost: vi.fn(),
  invokeWithError: vi.fn((fn: () => Promise<unknown>) => fn()),
}))

import { httpPost } from '../_utils'
import { ingestGetLogs } from '../ingest_queue'

const mockHttpPost = vi.mocked(httpPost)

describe('ingestGetLogs', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('unwraps the backend logs envelope into an iterable record list', async () => {
    const records = [
      {
        doc_id: 'doc-1',
        stage: 'moldet',
        level: 'info',
        message: 'detected structures',
        ts_ms: 1_000,
      },
    ]
    mockHttpPost.mockResolvedValue({ logs: records })

    await expect(ingestGetLogs('/library', 'doc-1', 200)).resolves.toEqual(records)
    expect(mockHttpPost).toHaveBeenCalledWith('/api/v1/pipeline/queue/logs', {
      library_root: '/library',
      doc_id: 'doc-1',
      limit: 200,
    })
  })

  it('returns an empty list when the backend omits logs', async () => {
    mockHttpPost.mockResolvedValue({ success: true, logs: null })

    await expect(ingestGetLogs('/library', 'doc-1')).resolves.toEqual([])
  })
})
