/**
 * environment.ts — resource manager wrappers (covered module at top).
 *
 * Keeps the two envelope mappings that are not plain forwarding: the
 * `{resources}` catalog unwrap and the nullable model-path result.
 */

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

  it('unwraps the resource catalog envelope and preserves nullable model paths', async () => {
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
    const env = await resourcesCheck()
    expect(httpGet).toHaveBeenCalledWith('/api/v1/environment/check')
    expect(env.summary).toBe('9/11 resources ready')

    mockHttpPost.mockResolvedValue(report.resources[0])
    await expect(resourcesStatus('torch')).resolves.toMatchObject({ id: 'torch', status: 'ready' })

    mockHttpPost.mockResolvedValue('/models/embedding')
    await expect(resourcesGetModelPath('embedding')).resolves.toBe('/models/embedding')
    mockHttpPost.mockResolvedValue(null)
    await expect(resourcesGetModelPath('nonexistent')).resolves.toBeNull()

    // Catalog entries are nested under `resources` and must be unwrapped.
    mockHttpPost.mockResolvedValue({
      resources: [
        { id: 'embedding', name: 'Qwen3-Embedding', type: 'model', description: 'test', size_mb: 1152, license: 'Apache-2.0', ms_repo: 'Qwen/Qwen3-Embedding-0.6B', pip_name: '' },
      ],
    })
    await expect(resourcesCatalog()).resolves.toHaveLength(1)
  })
})
