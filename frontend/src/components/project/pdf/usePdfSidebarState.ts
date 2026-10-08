/**
 * PDF viewer sidebar / results-pane UI state.
 *
 * Owns the collapse flag, the source-pane width lock, the active side tab, the
 * selected evidence id, the inline-editing detection index, and continuous
 * mode.
 *
 * None of these fields are written to storage today: the viewer's LRU snapshot
 * (``viewerSnapshots``) persists page / zoom / panels / detections only, so the
 * hook keeps them as plain component state.
 */

import { useCallback, useEffect, useState } from 'react'
import type { Dispatch, SetStateAction } from 'react'
import type { PageRenderInfo } from './usePdfNavigation'

export type PdfSidePaneTab = 'evidence' | 'molecules'

export interface UsePdfSidebarStateArgs {
  /** Current page render info; the source pane locks its width to it once known. */
  pageInfo: PageRenderInfo | null
}

export interface UsePdfSidebarStateResult {
  isResultPaneCollapsed: boolean
  setIsResultPaneCollapsed: Dispatch<SetStateAction<boolean>>
  sourcePaneWidth: number | null
  sidePaneTab: PdfSidePaneTab
  setSidePaneTab: Dispatch<SetStateAction<PdfSidePaneTab>>
  selectedEvidenceId: string | null
  setSelectedEvidenceId: Dispatch<SetStateAction<string | null>>
  editingDetectionIndex: number | null
  setEditingDetectionIndex: Dispatch<SetStateAction<number | null>>
  continuousMode: boolean
  toggleContinuousMode: () => void
}

export function usePdfSidebarState({
  pageInfo,
}: UsePdfSidebarStateArgs): UsePdfSidebarStateResult {
  const [isResultPaneCollapsed, setIsResultPaneCollapsed] = useState(false)
  const [sourcePaneWidth, setSourcePaneWidth] = useState<number | null>(null)
  const [sidePaneTab, setSidePaneTab] = useState<PdfSidePaneTab>('evidence')
  const [selectedEvidenceId, setSelectedEvidenceId] = useState<string | null>(null)
  const [editingDetectionIndex, setEditingDetectionIndex] = useState<number | null>(null)
  const [continuousMode, setContinuousMode] = useState(false)

  // Lock the source pane to the rendered page width the first time it is known.
  useEffect(() => {
    if (!pageInfo || !pageInfo.width || sourcePaneWidth === pageInfo.width) return
    setSourcePaneWidth(pageInfo.width)
  }, [pageInfo, sourcePaneWidth])

  const toggleContinuousMode = useCallback(() => setContinuousMode(mode => !mode), [])

  return {
    isResultPaneCollapsed, setIsResultPaneCollapsed,
    sourcePaneWidth,
    sidePaneTab, setSidePaneTab,
    selectedEvidenceId, setSelectedEvidenceId,
    editingDetectionIndex, setEditingDetectionIndex,
    continuousMode, toggleContinuousMode,
  }
}
