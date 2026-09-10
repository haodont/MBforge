import { describe, it, expect, beforeEach } from 'vitest'
import { StrictMode } from 'react'
import { renderHook, act } from '@testing-library/react'
import { useAppContext, AppProvider } from '../AppContext'
import type { ReactNode } from 'react'

function renderCtx() {
  return renderHook(() => useAppContext(), {
    wrapper: ({ children }: { children: ReactNode }) => (
      <AppProvider>{children}</AppProvider>
    ),
  })
}

describe('AppContext', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  it('starts with empty library root', () => {
    const { result } = renderCtx()
    expect(result.current.libraryRoot).toBe('')
  })

  it('setLibraryRoot updates root and resets tabs', () => {
    const { result } = renderCtx()

    // Open a tab first.
    act(() => {
      result.current.openTab({
        type: 'document',
        title: 'Test',
        doc: { doc_id: 'd1', path: 't.pdf', doc_type: 'pdf', title: 'Test' },
        libraryRoot: '/old',
      })
    })
    expect(result.current.openTabs.length).toBe(1)

    // Change library root — must clear tabs.
    act(() => {
      result.current.setLibraryRoot('/new')
    })
    expect(result.current.libraryRoot).toBe('/new')
    expect(result.current.openTabs.length).toBe(0)
    expect(result.current.activeTabId).toBeNull()
  })

  it('openTab adds tab when new', () => {
    const { result } = renderCtx()

    act(() => {
      result.current.openTab({
        type: 'document',
        title: 'Doc 1',
        doc: { doc_id: 'd1', path: 't.pdf', doc_type: 'pdf', title: 'Doc 1' },
        libraryRoot: '/lib',
      })
    })

    expect(result.current.openTabs.length).toBe(1)
    expect(result.current.activeTabId).toBe(result.current.openTabs[0].id)
  })

  it('keeps the active tab aligned with the tab list under StrictMode', () => {
    const { result } = renderHook(() => useAppContext(), {
      wrapper: ({ children }: { children: ReactNode }) => (
        <StrictMode>
          <AppProvider>{children}</AppProvider>
        </StrictMode>
      ),
    })

    act(() => {
      result.current.openTab({
        type: 'document',
        title: 'Strict mode document',
        doc: { doc_id: 'strict-doc', path: 'strict.pdf', doc_type: 'pdf', title: 'Strict mode document' },
        libraryRoot: '/lib',
      })
    })

    expect(result.current.openTabs).toHaveLength(1)
    expect(result.current.activeTabId).toBe(result.current.openTabs[0].id)
  })

  it('openTab activates existing tab instead of duplicating', () => {
    const { result } = renderCtx()

    act(() => {
      result.current.openTab({
        type: 'document',
        title: 'Same Doc',
        doc: { doc_id: 'd1', path: 't.pdf', doc_type: 'pdf', title: 'Same Doc' },
        libraryRoot: '/lib',
      })
    })
    const firstId = result.current.activeTabId

    act(() => {
      result.current.openTab({
        type: 'document',
        title: 'Same Doc',
        doc: { doc_id: 'd1', path: 't.pdf', doc_type: 'pdf', title: 'Same Doc' },
        libraryRoot: '/lib',
      })
    })

    expect(result.current.openTabs.length).toBe(1)
    expect(result.current.activeTabId).toBe(firstId)
  })

  it('closeTab removes tab and activates neighbour', () => {
    const { result } = renderCtx()

    act(() => {
      result.current.openTab({
        type: 'document', title: 'A', libraryRoot: '/lib',
        doc: { doc_id: 'a', path: 'a.pdf', doc_type: 'pdf', title: 'A' },
      })
      result.current.openTab({
        type: 'document', title: 'B', libraryRoot: '/lib',
        doc: { doc_id: 'b', path: 'b.pdf', doc_type: 'pdf', title: 'B' },
      })
    })
    expect(result.current.openTabs.length).toBe(2)

    const firstId = result.current.openTabs[0].id
    act(() => { result.current.closeTab(firstId) })
    expect(result.current.openTabs.length).toBe(1)
  })

})
