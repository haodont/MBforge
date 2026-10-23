import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

import { httpFetch, API_BASE, invokeWithError, registerGlobalErrorHandlers } from '../_utils'
import { AppError, ErrorCode, Severity } from '@/utils/errors'

describe('invokeWithError', () => {
  it('resolves the wrapped value and re-throws AppErrors unchanged', async () => {
    await expect(invokeWithError(() => Promise.resolve('ok'))).resolves.toBe('ok')

    const original = new AppError(ErrorCode.PdfParse, 'parse failed')
    await expect(invokeWithError(() => Promise.reject(original))).rejects.toBe(original)
  })

  it('wraps any rejection into an AppError with the fallback code and original message', async () => {
    await expect(invokeWithError(() => Promise.reject(new Error('boom'))))
      .rejects
      .toMatchObject({ errorCode: ErrorCode.Unknown, message: 'boom' })

    await expect(invokeWithError(() => Promise.reject(new Error('boom')), ErrorCode.Network))
      .rejects
      .toMatchObject({ errorCode: ErrorCode.Network, message: 'boom' })

    // Non-Error rejections must not crash the wrapper.
    const cases: Array<{ value: unknown, expected: string }> = [
      { value: 'plain string error', expected: 'plain string error' },
      { value: null, expected: 'null' },
      { value: { reason: 'structured failure' }, expected: '[object Object]' },
      { value: undefined, expected: 'undefined' },
    ]
    for (const { value, expected } of cases) {
      await expect(invokeWithError(() => {
        // Intentionally exercising the non-Error rejection handling path.
        throw value
      }, ErrorCode.ApiError))
        .rejects
        .toMatchObject({ errorCode: ErrorCode.ApiError, message: expected })
    }
  })
})

describe('registerGlobalErrorHandlers', () => {
  it('attaches error and unhandledrejection listeners and returns a cleanup function', () => {
    const addSpy = vi.spyOn(window, 'addEventListener')
    const removeSpy = vi.spyOn(window, 'removeEventListener')

    const cleanup = registerGlobalErrorHandlers()

    expect(addSpy).toHaveBeenCalledWith('error', expect.any(Function))
    expect(addSpy).toHaveBeenCalledWith('unhandledrejection', expect.any(Function))

    cleanup()

    expect(removeSpy).toHaveBeenCalledWith('error', expect.any(Function))
    expect(removeSpy).toHaveBeenCalledWith('unhandledrejection', expect.any(Function))

    addSpy.mockRestore()
    removeSpy.mockRestore()
  })
})

/**
 * httpFetch error contract tests.
 *
 * The frontend extracts `error_code` / `severity` / `category` / `context`
 * / `timestamp` from the server JSON body and propagates them into AppError.
 * Non-JSON bodies fall back to the legacy ErrorCode.Network.
 */

describe('httpFetch (JSON error body)', () => {
  const originalFetch = globalThis.fetch
  beforeEach(() => {
    vi.restoreAllMocks()
  })
  afterEach(() => {
    globalThis.fetch = originalFetch
  })

  it('extracts error_code / severity / category / timestamp from a JSON body', async () => {
    const payload = {
      success: false,
      error: 'root path is required',
      error_code: 'validation_error',
      severity: 'warning',
      category: 'mbforge.utils.helpers',
      context: { field: 'root' },
      timestamp: 1717700000.5,
    }
    globalThis.fetch = vi.fn(() =>
      Promise.resolve(new Response(JSON.stringify(payload), {
        status: 422,
        statusText: 'Unprocessable Entity',
        headers: { 'Content-Type': 'application/json' },
      })),
    )

    await expect(httpFetch('/api/v1/library/open', { method: 'POST' })).rejects.toMatchObject({
      errorCode: ErrorCode.ApiError, // backendCodeToErrorCode maps validation_error → ApiError
      message: 'root path is required',
      severity: Severity.Warning,
      category: 'mbforge.utils.helpers',
      context: expect.objectContaining({
        field: 'root',
        http_status: 422,
        backend_code: 'validation_error',
      }),
      timestamp: 1717700000.5,
    })
  })

  it('falls back to ErrorCode.Network when the body is not JSON', async () => {
    globalThis.fetch = vi.fn(() =>
      Promise.resolve(new Response('<html>502 Bad Gateway</html>', {
        status: 502,
        statusText: 'Bad Gateway',
        headers: { 'Content-Type': 'text/html' },
      })),
    )

    await expect(httpFetch('/api/v1/moldet/something')).rejects.toMatchObject({
      errorCode: ErrorCode.Network,
      severity: Severity.Error,
      context: expect.objectContaining({ http_status: 502 }),
    })
  })

  it('maps HTTP 503 to ModelNotAvailable when the server says so', async () => {
    const payload = {
      success: false,
      error: 'MolParser 模型未找到',
      error_code: 'model_not_available',
      severity: 'error',
      category: 'backends.molparser',
      timestamp: 1717700001.0,
    }
    globalThis.fetch = vi.fn(() =>
      Promise.resolve(new Response(JSON.stringify(payload), {
        status: 503,
        statusText: 'Service Unavailable',
        headers: { 'Content-Type': 'application/json' },
      })),
    )

    await expect(httpFetch('/api/v1/models/molparser/health')).rejects.toMatchObject({
      errorCode: ErrorCode.ModelNotAvailable,
      severity: Severity.Error,
      category: 'backends.molparser',
    })
  })

  it('falls back to status-derived severity when the body omits it', async () => {
    // Body has only `error_code`; severity defaults to severityFromHttpStatus(403) = Warning.
    globalThis.fetch = vi.fn(() =>
      Promise.resolve(new Response(JSON.stringify({ success: false, error: 'forbidden', error_code: 'path_traversal' }), {
        status: 403,
        statusText: 'Forbidden',
        headers: { 'Content-Type': 'application/json' },
      })),
    )

    await expect(httpFetch('/api/v1/library/foo')).rejects.toMatchObject({
      severity: Severity.Warning,
    })
  })
})

describe('httpFetch request construction', () => {
  const originalFetch = globalThis.fetch
  /** The ``RequestInit`` handed to the most recent ``fetch`` call. */
  const lastInit = (): RequestInit => {
    const calls = vi.mocked(globalThis.fetch).mock.calls
    const init = calls[calls.length - 1]?.[1]
    if (!init) throw new Error('fetch was not called')
    return init
  }
  beforeEach(() => {
    vi.restoreAllMocks()
    globalThis.fetch = vi.fn(() =>
      Promise.resolve(new Response('{}', { status: 200, statusText: 'OK' })),
    )
  })
  afterEach(() => {
    globalThis.fetch = originalFetch
  })

  it('builds the URL, headers and signal contract for every request shape', async () => {
    expect(API_BASE).toBe('/api/v1')

    // A caller-supplied API path is not double-prefixed.
    await httpFetch('/api/v1/sidecar/status', { method: 'GET' })
    expect(globalThis.fetch).toHaveBeenLastCalledWith('/api/v1/sidecar/status', expect.any(Object))

    // Bodiless request: no Content-Type is injected.
    await httpFetch('/api/v1/test', { method: 'GET' })
    let init = lastInit()
    expect(new Headers(init.headers).get('Content-Type')).toBeNull()

    // String body: JSON content type is injected.
    await httpFetch('/api/v1/test', { method: 'POST', body: '{"foo":1}' })
    init = lastInit()
    expect(new Headers(init.headers).get('Content-Type')).toBe('application/json')

    // An explicit Content-Type always wins.
    await httpFetch('/api/v1/test', {
      method: 'POST',
      body: '{"foo":1}',
      headers: { 'Content-Type': 'application/vnd.mbforge+json' },
    })
    init = lastInit()
    expect(new Headers(init.headers).get('Content-Type')).toBe('application/vnd.mbforge+json')

    // FormData must keep the browser-generated multipart boundary.
    const fd = new FormData()
    await httpFetch('/api/v1/upload', { method: 'POST', body: fd })
    init = lastInit()
    expect(new Headers(init.headers).get('Content-Type')).toBeNull()

    // The abort signal is forwarded untouched.
    const controller = new AbortController()
    await httpFetch('/api/v1/test', { signal: controller.signal })
    init = lastInit()
    expect(init.signal).toBe(controller.signal)

    // VITE_API_BASE replaces the default base for freshly evaluated modules.
    // Static import cannot work here: the module reads the env at evaluation
    // time, so the boundary must be re-evaluated under a stubbed env value.
    const previous = import.meta.env.VITE_API_BASE
    import.meta.env.VITE_API_BASE = '/custom/api'
    vi.resetModules()
    const { API_BASE: dynamicBase, httpFetch: dynamicFetch } = await import('../_utils')
    await dynamicFetch('/ping')
    expect(dynamicBase).toBe('/custom/api')
    expect(globalThis.fetch).toHaveBeenLastCalledWith('/custom/api/ping', expect.any(Object))
    import.meta.env.VITE_API_BASE = previous
  })
})

describe('httpFetch Pydantic 422 handling', () => {
  it('throws ApiError with joined detail messages for Pydantic validation errors', async () => {
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 422,
      text: () =>
        Promise.resolve(JSON.stringify({
          detail: [
            { loc: ['body', 'title'], msg: 'field required', type: 'missing' },
            { loc: ['body', 'page'], msg: 'value is not a valid integer', type: 'type_error' },
          ],
        })),
    })

    await expect(httpFetch('/api/v1/test', { method: 'POST', body: '{}' })).rejects.toThrow(
      AppError,
    )
    await expect(httpFetch('/api/v1/test', { method: 'POST', body: '{}' })).rejects.toSatisfy(
      (err: AppError) =>
        err.errorCode === ErrorCode.ApiError &&
        err.message.includes('body.title: field required') &&
        err.message.includes('body.page: value is not a valid integer'),
    )
  })
})
