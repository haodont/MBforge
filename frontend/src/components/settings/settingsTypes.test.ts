import { describe, expect, it } from 'vitest'
import { flattenSettings, isSettingsEqual, toBackendPayload } from './types'

describe('Local layout settings', () => {
  it('round-trips saved layout parameters through the settings state', () => {
    const state = flattenSettings({
      layout: { conf_threshold: 0.55, read_text: false, cross_model: false },
    })

    expect(state.layout_conf_threshold).toBe(0.55)
    expect(state.layout_read_text).toBe(false)
    expect(state.layout_cross_model).toBe(false)
    expect(toBackendPayload(state).layout).toEqual({
      conf_threshold: 0.55,
      read_text: false,
      cross_model: false,
    })
  })

  it('uses the producer defaults when the backend omits layout', () => {
    const state = flattenSettings({})

    expect(state.layout_conf_threshold).toBe(0.4)
    expect(state.layout_read_text).toBe(true)
    expect(state.layout_cross_model).toBe(true)
  })

  it('keeps the model cache path in the staged settings payload', () => {
    const state = flattenSettings({ model_cache_dir: 'C:/models' })
    const changed = { ...state, model_cache_dir: 'D:/mbforge-cache' }

    expect(isSettingsEqual(state, changed)).toBe(false)
    expect(toBackendPayload(changed).model_cache_dir).toBe('D:/mbforge-cache')
  })
})
