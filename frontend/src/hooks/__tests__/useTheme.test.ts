/**
 * useTheme.ts / initTheme (covered module at top).
 *
 * Protects the theme resolution contract: stored value wins, an absent value
 * resolves through the system preference, and every application path writes
 * both localStorage and the `data-theme` attribute the CSS depends on.
 */

import { describe, it, expect, beforeEach, vi } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { useTheme, initTheme } from '../useTheme'

const THEME_KEY = 'mbforge_theme'

function stubMatchMedia(prefersDark: boolean) {
  vi.stubGlobal('matchMedia', (query: string) => ({
    matches: query === `(prefers-color-scheme: ${prefersDark ? 'dark' : 'light'})`,
    media: query,
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => false,
  }))
}

describe('useTheme', () => {
  beforeEach(() => {
    localStorage.clear()
    document.documentElement.removeAttribute('data-theme')
    stubMatchMedia(true)
  })

  it('defaults to system, honours a stored value, and persists setTheme', () => {
    const initial = renderHook(() => useTheme())
    expect(initial.result.current.theme).toBe('system')
    expect(document.documentElement.getAttribute('data-theme')).toBe('dark')

    stubMatchMedia(false)
    const lightSystem = renderHook(() => useTheme())
    expect(lightSystem.result.current.theme).toBe('system')
    expect(document.documentElement.getAttribute('data-theme')).toBe('light')

    localStorage.setItem(THEME_KEY, 'light')
    const stored = renderHook(() => useTheme())
    expect(stored.result.current.theme).toBe('light')
    expect(document.documentElement.getAttribute('data-theme')).toBe('light')

    act(() => {
      stored.result.current.setTheme('dark')
    })
    expect(stored.result.current.theme).toBe('dark')
    expect(localStorage.getItem(THEME_KEY)).toBe('dark')
    expect(document.documentElement.getAttribute('data-theme')).toBe('dark')
  })

  it('initTheme applies the resolved theme without mounting the hook', () => {
    localStorage.setItem(THEME_KEY, 'system')
    initTheme()
    expect(document.documentElement.getAttribute('data-theme')).toBe('dark')
  })
})
