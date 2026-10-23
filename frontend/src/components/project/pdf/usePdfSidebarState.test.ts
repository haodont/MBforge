import { act, renderHook } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { usePdfSidebarState } from './usePdfSidebarState'

describe('usePdfSidebarState', () => {
  it('selects a requested pane when a task result is opened again', () => {
    const { result, rerender } = renderHook(
      ({ requestId }: { requestId?: string }) => usePdfSidebarState({
        pageInfo: null,
        initialSidePaneTab: 'analysis',
        sidePaneRequestId: requestId,
      }),
      { initialProps: { requestId: 'first-open' } },
    )

    expect(result.current.sidePaneTab).toBe('analysis')
    act(() => {
      result.current.setSidePaneTab('evidence')
      result.current.setIsResultPaneCollapsed(true)
    })
    rerender({ requestId: 'reopen' })

    expect(result.current.sidePaneTab).toBe('analysis')
    expect(result.current.isResultPaneCollapsed).toBe(false)
  })
})
