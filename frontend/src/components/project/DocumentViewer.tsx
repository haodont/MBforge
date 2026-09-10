import { lazy, Suspense, useCallback, useRef, useState } from 'react'
import PdfViewer, { type PdfViewerHandle } from './PdfViewer'
import type { DocumentEntry, MoleculeRecord } from '@/types'
import { moleculeByLocation } from '@/api/http/molecule'
import { molAdminGet } from '@/api/http/molecule_admin'
const MoleculeDetailDrawer = lazy(() => import('@/components/molecule/MoleculeDetailDrawer'))

interface Props {
  doc: DocumentEntry
  libraryRoot: string
  onClose: () => void
  initialPage?: number
  initialBbox?: [number, number, number, number]
  viewerKey?: string
}

export default function DocumentViewer({
  doc,
  libraryRoot,
  onClose,
  initialPage,
  initialBbox,
  viewerKey,
}: Props) {
  const pdfRef = useRef<PdfViewerHandle>(null)
  const [selectedMolecule, setSelectedMolecule] = useState<MoleculeRecord | null>(null)

  const handleMoleculeClick = useCallback(async (info: {
    page: number
    bbox?: [number, number, number, number] | null
  }) => {
    pdfRef.current?.setCurrentPage(info.page)
    if (!info.bbox) return
    try {
      const matches = await moleculeByLocation(libraryRoot, doc.doc_id, info.page, info.bbox)
      const molId = matches.find(match => match.mol_id)?.mol_id
      if (!molId) return
      const molecule = await molAdminGet(libraryRoot, molId)
      if (molecule) setSelectedMolecule(molecule)
    } catch {
      // A viewer click remains useful even if the optional reverse lookup fails.
    }
  }, [doc.doc_id, libraryRoot])

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
