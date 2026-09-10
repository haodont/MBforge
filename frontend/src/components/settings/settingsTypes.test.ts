import { describe, expect, it } from 'vitest'
import { flattenSettings, isSettingsEqual, toBackendPayload } from './types'

describe('OCR priority settings', () => {
  it('round-trips a saved provider order through the settings state', () => {
    const state = flattenSettings({
      ocr: { priority: ['paddleocr'] },
    })

    expect(state.ocr_priority).toEqual(['paddleocr'])
    expect((toBackendPayload(state).ocr as { priority: string[] }).priority).toEqual(
      ['paddleocr'],
    )
  })

  it('uses the stable default order when the backend omits priority', () => {
    expect(flattenSettings({}).ocr_priority).toEqual(['paddleocr'])
  })

  it('keeps the model cache path in the staged settings payload', () => {
    const state = flattenSettings({ model_cache_dir: 'C:/models' })
    const changed = { ...state, model_cache_dir: 'D:/mbforge-cache' }

    expect(isSettingsEqual(state, changed)).toBe(false)
    expect(toBackendPayload(changed).model_cache_dir).toBe('D:/mbforge-cache')
  })
})
