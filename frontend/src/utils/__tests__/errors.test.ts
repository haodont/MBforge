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
  it('keeps the legacy constructor shapes and serializes every extended field', () => {
    // 2-arg (no opts): nothing extended is set.
    const legacy = new AppError(ErrorCode.PdfParse, 'parse failed')
    expect(legacy.errorCode).toBe(ErrorCode.PdfParse)
    expect(legacy.message).toBe('parse failed')
    expect(legacy.severity).toBeUndefined()
    expect(legacy.category).toBeUndefined()
    expect(legacy.context).toBeUndefined()

    // Legacy callers pass a raw context bag as the 3rd arg; it must be treated
    // as context when severity/category/timestamp are absent.
    const withContext = new AppError(ErrorCode.PdfParse, 'parse failed', { file: 'a.pdf' })
    expect(withContext.context).toEqual({ file: 'a.pdf' })
    expect(withContext.severity).toBeUndefined()

    const extended = new AppError(ErrorCode.ApiError, 'boom', {
      severity: Severity.Fatal,
      category: 'pipeline.runner',
      context: { step: 3 },
      timestamp: 2.0,
    })
    expect(extended.severity).toBe(Severity.Fatal)
    expect(extended.category).toBe('pipeline.runner')
    expect(extended.context).toEqual({ step: 3 })
    expect(extended.timestamp).toBe(2.0)

    expect(extended.toJSON()).toEqual({
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
  it('passes AppErrors through and wraps plain/non-Error values with the fallback code', () => {
    const original = new AppError(ErrorCode.PdfParse, 'parse', { severity: Severity.Warning })
    expect(toAppError(original)).toBe(original)

    const wrapped = toAppError(new Error('boom'), ErrorCode.Network)
    expect(wrapped.errorCode).toBe(ErrorCode.Network)
    expect(wrapped.message).toBe('boom')

    const cases: Array<[unknown, string]> = [
      ['raw', 'raw'],
      [null, 'null'],
      [undefined, 'undefined'],
    ]
    for (const [value, expected] of cases) {
      expect(toAppError(value).message, String(value)).toBe(expected)
    }

    expect(toAppError(new Error('boom'), ErrorCode.Network, { severity: Severity.Fatal }).severity)
      .toBe(Severity.Fatal)
  })
})

describe('severityFromHttpStatus', () => {
  it('maps each status band to its severity', () => {
    const cases: Array<[number, Severity]> = [
      [400, Severity.Warning],
      [403, Severity.Warning],
      [404, Severity.Info],
      [422, Severity.Warning],
      [500, Severity.Error],
      [503, Severity.Error],
      [999, Severity.Error],
    ]
    for (const [status, expected] of cases) {
      expect(severityFromHttpStatus(status), `status ${status}`).toBe(expected)
    }
  })
})

describe('getErrorMessage', () => {
  it('returns the localized message for known codes and falls back to Unknown', () => {
    expect(getErrorMessage(ErrorCode.Network)).toMatch(/网络/)
    expect(getErrorMessage(ErrorCode.ModelNotAvailable)).toMatch(/模型/)

    // @ts-expect-error — exercise the runtime fallback path
    expect(getErrorMessage('NOT_A_CODE')).toBe(getErrorMessage(ErrorCode.Unknown))
  })
})
