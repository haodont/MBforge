import { beforeAll, describe, it, expect } from 'vitest'

import i18n from '@/i18n'

import {
  AppError,
  ErrorCode,
  Severity,
  getErrorMessage,
  severityFromHttpStatus,
  toAppError,
} from '../errors'

beforeAll(async () => {
  await i18n.changeLanguage('zh')
})

describe('AppError', () => {
  it('preserves the legacy 2-arg constructor (no opts)', () => {
    const err = new AppError(ErrorCode.PdfParse, 'parse failed')
    expect(err.errorCode).toBe(ErrorCode.PdfParse)
    expect(err.message).toBe('parse failed')
    expect(err.severity).toBeUndefined()
    expect(err.category).toBeUndefined()
    expect(err.context).toBeUndefined()
  })

  it('accepts a positional context object as the 3rd arg (back-compat)', () => {
    // Legacy callers pass a raw context bag like `{ file: 'a.pdf' }`. We
    // accept this by treating the 3rd arg as context when severity/category/
    // timestamp are absent.
    const err = new AppError(ErrorCode.PdfParse, 'parse failed', { file: 'a.pdf' })
    expect(err.context).toEqual({ file: 'a.pdf' })
    expect(err.severity).toBeUndefined()
  })

  it('carries severity/category/context when constructed with opts', () => {
    const err = new AppError(ErrorCode.ApiError, 'boom', {
      severity: Severity.Warning,
      category: 'routers.library',
      context: { doc_id: 'abc' },
      timestamp: 1.7,
    })
    expect(err.severity).toBe(Severity.Warning)
    expect(err.category).toBe('routers.library')
    expect(err.context).toEqual({ doc_id: 'abc' })
    expect(err.timestamp).toBe(1.7)
  })

  it('toJSON includes all extended fields', () => {
    const err = new AppError(ErrorCode.ApiError, 'boom', {
      severity: Severity.Fatal,
      category: 'pipeline.runner',
      context: { step: 3 },
      timestamp: 2.0,
    })
    expect(err.toJSON()).toEqual({
      name: 'AppError',
      errorCode: ErrorCode.ApiError,
      message: 'boom',
      severity: Severity.Fatal,
      category: 'pipeline.runner',
      context: { step: 3 },
      timestamp: 2.0,
    })
  })
})

describe('toAppError', () => {
  it('returns the same AppError when given one', () => {
    const original = new AppError(ErrorCode.PdfParse, 'parse', { severity: Severity.Warning })
    expect(toAppError(original)).toBe(original)
  })

  it('wraps a plain Error using the fallback code', () => {
    const wrapped = toAppError(new Error('boom'), ErrorCode.Network)
    expect(wrapped.errorCode).toBe(ErrorCode.Network)
    expect(wrapped.message).toBe('boom')
  })

  it('wraps a non-Error value', () => {
    expect(toAppError('raw').message).toBe('raw')
    expect(toAppError(null).message).toBe('null')
    expect(toAppError(undefined).message).toBe('undefined')
  })

  it('attaches opts (severity) when wrapping a non-AppError', () => {
    const wrapped = toAppError(new Error('boom'), ErrorCode.Network, {
      severity: Severity.Fatal,
    })
    expect(wrapped.severity).toBe(Severity.Fatal)
  })
})

describe('severityFromHttpStatus', () => {
  it.each([
    [400, Severity.Warning],
    [403, Severity.Warning],
    [404, Severity.Info],
    [422, Severity.Warning],
    [500, Severity.Error],
    [503, Severity.Error],
    [999, Severity.Error],
  ])('maps status %i to %s', (status, expected) => {
    expect(severityFromHttpStatus(status)).toBe(expected)
  })
})

describe('getErrorMessage', () => {
  it('returns the user-facing string for known codes', () => {
    expect(getErrorMessage(ErrorCode.Network)).toMatch(/网络/)
    expect(getErrorMessage(ErrorCode.ModelNotAvailable)).toMatch(/模型/)
  })

  it('falls back to Unknown message for invalid codes', () => {
    // @ts-expect-error — exercise the runtime fallback path
    expect(getErrorMessage('NOT_A_CODE')).toBe(getErrorMessage(ErrorCode.Unknown))
  })
})
