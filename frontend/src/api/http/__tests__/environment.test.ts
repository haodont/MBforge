import { describe, it, expect, vi, beforeEach } from 'vitest'

vi.mock('../_utils', () => ({
  httpPost: vi.fn(),
  httpGet: vi.fn(),
  invokeWithError: vi.fn(async (fn: () => Promise<unknown>) => fn()),
}))

import { httpPost, httpGet } from '../_utils'
import { resourcesCheck, resourcesStatus, resourcesGetModelPath, resourcesCatalog } from '../environment'

const mockHttpPost = vi.mocked(httpPost)
const mockHttpGet = vi.mocked(httpGet)

describe('environment API', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  describe('resourcesCheck', () => {
    it('returns environment report', async () => {
      const report = {
        python_version: '3.14.2',
        gpu_available: true,
        gpu_name: 'RTX 5070',
        cuda_version: '12.8',
        summary: '9/11 resources ready',
        resources: [
          { id: 'torch', name: 'PyTorch', type: 'python_package', status: 'ready', local_path: '', size_mb: 0, version: '2.11.0', error: '' },
        ],
      }
      mockHttpGet.mockResolvedValue(report)

      const result = await resourcesCheck()

      expect(httpGet).toHaveBeenCalledWith('/api/v1/environment/check')
      expect(result.summary).toBe('9/11 resources ready')
      expect(result.resources).toHaveLength(1)
    })
  })

  describe('resourcesStatus', () => {
    it('returns single resource status', async () => {
      const status = { id: 'torch', name: 'PyTorch', type: 'python_package', status: 'ready', local_path: '', size_mb: 0, version: '2.11.0', error: '' }
      mockHttpPost.mockResolvedValue(status)

      const result = await resourcesStatus('torch')

      expect(httpPost).toHaveBeenCalledWith('/api/v1/resources/status', { resource_id: 'torch' })
      expect(result.status).toBe('ready')
    })
  })

  describe('resourcesGetModelPath', () => {
    it('returns model path when available', async () => {
      mockHttpPost.mockResolvedValue('/models/embedding')

      const result = await resourcesGetModelPath('embedding')

      expect(httpPost).toHaveBeenCalledWith('/api/v1/resources/model-path', { resource_id: 'embedding' })
      expect(result).toBe('/models/embedding')
    })

    it('returns null when not available', async () => {
      mockHttpPost.mockResolvedValue(null)

      const result = await resourcesGetModelPath('nonexistent')

      expect(result).toBeNull()
    })
  })

  describe('resourcesCatalog', () => {
    it('returns resource catalog', async () => {
      const catalog = [
        { id: 'embedding', name: 'Qwen3-Embedding', type: 'model', description: 'test', size_mb: 1152, license: 'Apache-2.0', ms_repo: 'Qwen/Qwen3-Embedding-0.6B', pip_name: '' },
      ]
      mockHttpPost.mockResolvedValue({ resources: catalog })

      const result = await resourcesCatalog()

      expect(httpPost).toHaveBeenCalledWith('/api/v1/resources/catalog')
      expect(result).toHaveLength(1)
    })
  })
})
