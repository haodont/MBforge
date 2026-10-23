import { useState } from 'react'
import { act, renderHook } from '@testing-library/react'
import { expect, it, vi } from 'vitest'
import { usePdfDeepLink } from './usePdfDeepLink'

it('selects a cross-page evidence target without trapping manual navigation and permits reopening it', () => {
  const ignore = vi.fn()
  const { result, rerender } = renderHook(({ requestId }: { requestId: number }) => {
    const [currentPage, setCurrentPage] = useState(1)
    const [selectedEvidenceId, setSelectedEvidenceId] = useState<string | null>(null)
    usePdfDeepLink({ initialPage: 2, initialEvidenceId: 'page-2-evidence', navigationRequestId: requestId,
      currentPage, setCurrentPage, pageInfo: null, scrollToDetection: ignore, setSelectedEvidenceId,
      setSelectedOcrIndex: ignore, setEditingDetectionIndex: ignore })
    return { currentPage, setCurrentPage, selectedEvidenceId }
  }, { initialProps: { requestId: 1 } })
  expect(result.current.currentPage).toBe(2)
  expect(result.current.selectedEvidenceId).toBe('page-2-evidence')
  act(() => result.current.setCurrentPage(1))
  expect(result.current.currentPage).toBe(1)
  expect(result.current.selectedEvidenceId).toBeNull()
  rerender({ requestId: 2 })
  expect(result.current.currentPage).toBe(2)
  expect(result.current.selectedEvidenceId).toBe('page-2-evidence')
})
