/**
 * Covers `AppProvider` / `useAppContext` (../AppContext): the open-tab
 * lifecycle (add, dedupe, fresh side-pane request, close, StrictMode), the
 * empty library-root default, and the tab reset when the library root changes.
 */
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

function renderStrictCtx() {
  return renderHook(() => useAppContext(), {
    wrapper: ({ children }: { children: ReactNode }) => (
      <StrictMode>
        <AppProvider>{children}</AppProvider>
      </StrictMode>
    ),
  })
}

function documentTab(title: string, docId: string, libraryRoot = '/lib') {
  return {
    type: 'document' as const,
    title,
    doc: { doc_id: docId, path: `${docId}.pdf`, doc_type: 'pdf', title },
    libraryRoot,
  }
}

describe('AppContext', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  it('opens, deduplicates and closes tabs', () => {
    const { result, unmount } = renderCtx()

    // A new tab is added and becomes active.
    act(() => {
      result.current.openTab(documentTab('Doc 1', 'd1'))
    })
    expect(result.current.openTabs.length).toBe(1)
    const firstId = result.current.openTabs[0].id
    expect(result.current.activeTabId).toBe(firstId)

    // Reopening the same document activates the existing tab instead of
    // duplicating it.
    act(() => {
      result.current.openTab(documentTab('Doc 1', 'd1'))
    })
    expect(result.current.openTabs.length).toBe(1)
    expect(result.current.activeTabId).toBe(firstId)

    // Reopening an existing PDF with a side-pane request must issue a fresh
    // navigation request id so the pane re-targets.
    const pdf = {
      type: 'pdf' as const,
      title: 'Patent',
      doc: { doc_id: 'patent-1', path: 'patent.pdf', doc_type: 'pdf', title: 'Patent' },
      libraryRoot: '/lib',
      initialSidePaneTab: 'analysis' as const,
    }
    act(() => { result.current.openTab(pdf) })
    const pdfTabId = result.current.openTabs[1].id
    const firstRequestId = result.current.openTabs[1].sidePaneRequestId
    act(() => { result.current.openTab(pdf) })

    expect(result.current.openTabs).toHaveLength(2)
    expect(result.current.openTabs[1].id).toBe(pdfTabId)
    expect(result.current.openTabs[1].sidePaneRequestId).not.toBe(firstRequestId)

    // Closing the first tab removes it from the set.
    act(() => { result.current.closeTab(firstId) })
    expect(result.current.openTabs.length).toBe(1)

    unmount()

    // StrictMode double-invocation must not desync the active tab from the list.
    const strict = renderStrictCtx()
    act(() => {
      strict.result.current.openTab(documentTab('Strict mode document', 'strict-doc'))
    })
    expect(strict.result.current.openTabs).toHaveLength(1)
    expect(strict.result.current.activeTabId).toBe(strict.result.current.openTabs[0].id)
  })

  it('starts with an empty library root and clears tabs when it changes', () => {
    const { result } = renderCtx()
    expect(result.current.libraryRoot).toBe('')

    // Open a tab first, then change the root — the tab set must be cleared.
    act(() => {
      result.current.openTab(documentTab('Test', 'd1', '/old'))
    })
    expect(result.current.openTabs.length).toBe(1)

    act(() => {
      result.current.setLibraryRoot('/new')
    })
    expect(result.current.libraryRoot).toBe('/new')
    expect(result.current.openTabs.length).toBe(0)
    expect(result.current.activeTabId).toBeNull()
  })
})
