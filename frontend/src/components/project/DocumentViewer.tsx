import { lazy, Suspense, useCallback, useEffect, useRef, useState } from 'react'
import PdfViewer, { type PdfViewerHandle } from './PdfViewer'
import type { DocumentEntry, MoleculeRecord } from '@/types'
import { useMolecule, useMoleculesByLocation } from '@/api/query/hooks'
const MoleculeDetailDrawer = lazy(() => import('@/components/molecule/MoleculeDetailDrawer'))

interface Props {
  doc: DocumentEntry
  libraryRoot: string
  onClose: () => void
  initialPage?: number
  initialBbox?: [number, number, number, number]
  initialEvidenceId?: string
  viewerKey?: string
}

export default function DocumentViewer({
  doc,
  libraryRoot,
  onClose,
  initialPage,
  initialBbox,
  initialEvidenceId,
  viewerKey,
}: Props) {
  const pdfRef = useRef<PdfViewerHandle>(null)
  const [selectedMolecule, setSelectedMolecule] = useState<MoleculeRecord | null>(null)
  // Most recent click target (page + bbox); drives the reverse molecule lookup.
  const [clickedLocation, setClickedLocation] = useState<{
    page: number
    bbox: [number, number, number, number]
  } | null>(null)
  const [molId, setMolId] = useState<string | null>(null)

  // Reverse lookup: location → molecule id → molecule record. Both requests
  // live in the query layer; a click only records the location, so a viewer
  // click stays useful even if the optional lookup fails.
  const { data: matches } = useMoleculesByLocation(
    libraryRoot,
    doc.doc_id,
    clickedLocation?.page ?? 0,
    clickedLocation?.bbox ?? null,
  )
  const { data: molecule } = useMolecule(libraryRoot, molId)

  useEffect(() => {
    if (!clickedLocation) return
    setMolId(matches?.find(match => match.mol_id)?.mol_id ?? null)
  }, [clickedLocation, matches])

  useEffect(() => {
    if (molecule) setSelectedMolecule(molecule)
  }, [molecule])

  const handleMoleculeClick = useCallback((info: {
    page: number
    bbox?: [number, number, number, number] | null
  }) => {
    pdfRef.current?.setCurrentPage(info.page)
    if (!info.bbox) return
    setClickedLocation({ page: info.page, bbox: info.bbox })
  }, [])

  return (
    <div className="document-viewer" style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      <div
        className="document-viewer-body"
        style={{
          flex: 1,
          display: 'flex',
          minHeight: 0,
          overflow: 'hidden',
        }}
      >
        <div className="document-viewer-pane">
          <PdfViewer
            ref={pdfRef}
            doc={doc}
            libraryRoot={libraryRoot}
            onClose={onClose}
            viewerKey={viewerKey}
            initialPage={initialPage}
            initialBbox={initialBbox}
            initialEvidenceId={initialEvidenceId}
            onMoleculeClick={handleMoleculeClick}
          />
        </div>
      </div>
      {selectedMolecule && (
        <Suspense fallback={null}>
          <MoleculeDetailDrawer
            molecule={selectedMolecule}
            open
            libraryRoot={libraryRoot}
            onClose={() => setSelectedMolecule(null)}
          />
        </Suspense>
      )}
    </div>
  )
}
