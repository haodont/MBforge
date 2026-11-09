import { beforeEach, describe, expect, it } from 'vitest'
import {
  loadPersistedViewerState,
  savePersistedViewerState,
  type PersistedViewerState,
} from '../viewerSnapshots'

const state: PersistedViewerState = {
  currentPage: 42,
  pdfScale: 0.75,
  showTextLayer: false,
  showMoleculeOverlay: true,
  showOcrOverlay: false,
  continuousMode: true,
}

describe('viewerSnapshots persistence', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  it('round-trips the reload-safe viewer state', () => {
    savePersistedViewerState('doc-1', state)
    expect(loadPersistedViewerState('doc-1')).toEqual(state)
  })

  it('ignores malformed or incomplete records', () => {
    localStorage.setItem('mbforge.pdf.viewer.doc-1', '{"currentPage":3}')
    expect(loadPersistedViewerState('doc-1')).toBeNull()
    localStorage.setItem('mbforge.pdf.viewer.doc-1', 'not json')
    expect(loadPersistedViewerState('doc-1')).toBeNull()
  })
})
