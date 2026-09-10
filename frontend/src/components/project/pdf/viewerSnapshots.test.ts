import { describe, it, expect, afterEach } from 'vitest'
import {
  viewerSnapshots,
  clearViewerSnapshotsForDoc,
  type PdfViewerSnapshot,
} from './viewerSnapshots'

const snapshot: PdfViewerSnapshot = {
  currentPage: 1,
  pdfScale: 1,
  showTextLayer: false,
  showTextPanel: false,
  showOcrPanel: false,
  selectedDetection: null,
  pageDetections: [],
  ocrBlocks: [],
}

describe('clearViewerSnapshotsForDoc', () => {
  afterEach(() => {
    for (const key of viewerSnapshots.keys()) viewerSnapshots.delete(key)
  })

  it('purges only the snapshots whose key ends with the doc id', () => {
    const keep = 'tab-a:doc-other'
    const mineA = 'tab-b:doc-target'
    const mineB = 'tab-c:doc-target'
    for (const key of [keep, mineA, mineB]) viewerSnapshots.set(key, snapshot)

    clearViewerSnapshotsForDoc('doc-target')

    expect(viewerSnapshots.has(mineA)).toBe(false)
    expect(viewerSnapshots.has(mineB)).toBe(false)
    expect(viewerSnapshots.has(keep)).toBe(true)
  })

  it('leaves unrelated snapshots alone', () => {
    const unrelated = 'tab-a:doc-target-other'
    const keep = 'tab-x:doc-target'
    viewerSnapshots.set(unrelated, snapshot)
    viewerSnapshots.set(keep, snapshot)

    clearViewerSnapshotsForDoc('doc-target-e')
    // doc-target-other does not end with doc-tar… doc id `doc-target-e`; keep is untouched.
    expect(viewerSnapshots.has(unrelated)).toBe(true)
    expect(viewerSnapshots.has(keep)).toBe(true)
  })

  it('is a no-op for an empty doc id', () => {
    viewerSnapshots.set('tab-a:doc-target', snapshot)
    clearViewerSnapshotsForDoc('')
    expect(viewerSnapshots.has('tab-a:doc-target')).toBe(true)
  })
})