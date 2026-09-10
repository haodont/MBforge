import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

import { httpFetch, API_BASE, invokeWithError, registerGlobalErrorHandlers } from '../_utils'
import { AppError, ErrorCode, Severity } from '@/utils/errors'

describe('invokeWithError', () => {
  it('returns resolved value on success', async () => {
    const result = await invokeWithError(() => Promise.resolve('ok'))

    expect(result).toBe('ok')
  })

  it('throws AppError on rejection with original message', async () => {
    await expect(invokeWithError(() => Promise.reject(new Error('boom'))))
      .rejects
      .toBeInstanceOf(AppError)

    await expect(invokeWithError(() => Promise.reject(new Error('boom'))))
      .rejects
      .toMatchObject({ message: 'boom' })
  })

  it('uses default Unknown fallback when no fallback provided', async () => {
    await expect(invokeWithError(() => Promise.reject(new Error('boom'))))
      .rejects
      .toMatchObject({ errorCode: ErrorCode.Unknown, message: 'boom' })
  })

  it('wraps non-AppError with the fallback error code', async () => {
    await expect(invokeWithError(() => Promise.reject(new Error('boom')), ErrorCode.Network))
      .rejects
      .toMatchObject({ errorCode: ErrorCode.Network, message: 'boom' })
  })

  it('re-throws AppError without re-wrapping', async () => {
    const original = new AppError(ErrorCode.PdfParse, 'parse failed')

    await expect(invokeWithError(() => Promise.reject(original)))
      .rejects
      .toBe(original)
  })

  it.each([
    { label: 'string', value: 'plain string error', expected: 'plain string error' },
    { label: 'null', value: null, expected: 'null' },
    { label: 'object', value: { reason: 'structured failure' }, expected: '[object Object]' },
    { label: 'undefined', value: undefined, expected: 'undefined' },
  ])('wraps $label rejection value as AppError', async ({ value, expected }) => {
    await expect(invokeWithError(() => {
      // Intentionally exercising the non-Error rejection handling path.
      // eslint-disable-next-line @typescript-eslint/only-throw-error
      throw value
    }, ErrorCode.ApiError))
      .rejects
      .toMatchObject({ errorCode: ErrorCode.ApiError, message: expected })
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
 * httpFetch JSON error-body contract tests.
 *
 * The frontend now extracts `error_code` / `severity` / `category` / `context`
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
  beforeEach(() => {
    vi.restoreAllMocks()
    globalThis.fetch = vi.fn(() =>
      Promise.resolve(new Response('{}', { status: 200, statusText: 'OK' })),
    )
  })
  afterEach(() => {
    globalThis.fetch = originalFetch
  })

  it('defaults API_BASE to /api/v1', () => {
    expect(API_BASE).toBe('/api/v1')
  })

  it('does not duplicate API_BASE when callers pass a full API path', async () => {
    await httpFetch('/api/v1/sidecar/status', { method: 'GET' })
    expect(globalThis.fetch).toHaveBeenCalledWith('/api/v1/sidecar/status', expect.any(Object))
  })

  it('uses VITE_API_BASE from import.meta.env when present', async () => {
    const previous = import.meta.env.VITE_API_BASE
    import.meta.env.VITE_API_BASE = '/custom/api'
    // Force a fresh module evaluation so API_BASE is recomputed.
    vi.resetModules()
    const { API_BASE: dynamicBase, httpFetch: dynamicFetch } = await import('../_utils')
    globalThis.fetch = vi.fn(() => Promise.resolve(new Response('{}', { status: 200 })))
    await dynamicFetch('/ping')
    expect(dynamicBase).toBe('/custom/api')
    expect(globalThis.fetch).toHaveBeenCalledWith('/custom/api/ping', expect.any(Object))
    import.meta.env.VITE_API_BASE = previous
  })

  it('does not set Content-Type for requests without a body', async () => {
    await httpFetch('/api/v1/test', { method: 'GET' })
    const init = (globalThis.fetch as unknown as ReturnType<typeof vi.fn>).mock.calls[0][1] as RequestInit
    expect(new Headers(init.headers).get('Content-Type')).toBeNull()
  })

  it('sets Content-Type to application/json for string bodies', async () => {
    await httpFetch('/api/v1/test', { method: 'POST', body: '{"foo":1}' })
    const init = (globalThis.fetch as unknown as ReturnType<typeof vi.fn>).mock.calls[0][1] as RequestInit
    expect(new Headers(init.headers).get('Content-Type')).toBe('application/json')
  })

  it('preserves an explicitly provided Content-Type header', async () => {
    await httpFetch('/api/v1/test', {
      method: 'POST',
      body: '{"foo":1}',
      headers: { 'Content-Type': 'application/vnd.mbforge+json' },
    })
    const init = (globalThis.fetch as unknown as ReturnType<typeof vi.fn>).mock.calls[0][1] as RequestInit
    expect(new Headers(init.headers).get('Content-Type')).toBe('application/vnd.mbforge+json')
  })

  it('does not set Content-Type for FormData bodies', async () => {
    const fd = new FormData()
    await httpFetch('/api/v1/upload', { method: 'POST', body: fd })
    const init = (globalThis.fetch as unknown as ReturnType<typeof vi.fn>).mock.calls[0][1] as RequestInit
    expect(new Headers(init.headers).get('Content-Type')).toBeNull()
  })

  it('passes an AbortSignal to fetch', async () => {
    const controller = new AbortController()
    await httpFetch('/api/v1/test', { signal: controller.signal })
    const init = (globalThis.fetch as unknown as ReturnType<typeof vi.fn>).mock.calls[0][1] as RequestInit
    expect(init.signal).toBe(controller.signal)
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
