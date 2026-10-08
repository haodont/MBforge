import Modal from '@/components/ui/Modal'
import MoleculeDetailPanel from './MoleculeDetailPanel'
import { showToast } from '@/hooks/useToast'
import { useAppContext } from '@/context/AppContext'
import type { EvidenceItem, MoleculeRecord } from '@/types'
import type { DocumentEntry } from '@/types'

interface MoleculeDetailDrawerProps {
  molecule: MoleculeRecord | null
  open: boolean
  libraryRoot: string | null
  onClose: () => void
  onSaved?: () => void
}

export default function MoleculeDetailDrawer({
  molecule,
  open,
  libraryRoot,
  onClose,
  onSaved,
}: MoleculeDetailDrawerProps) {
  const { openTab } = useAppContext()

  const handleOpenPdf = (
    docId: string,
    page: number | null,
    bbox: EvidenceItem['bbox'],
    evidenceId?: string | null,
  ) => {
    if (!libraryRoot) {
      showToast('未指定 library_root', 'error')
      return
    }
    // Build a minimal DocumentEntry so openTab accepts it. The PDF viewer
    // resolves the canonical source artifact from the library root.
    const sourcePath = `storage/${docId}/source.pdf`
    const stub: DocumentEntry = {
      doc_id: docId,
      path: sourcePath,
      source_path: sourcePath,
      doc_type: 'pdf',
      title: docId,
      added_at: new Date().toISOString(),
      hash: '',
    }
    openTab({
      type: 'document',
      title: docId,
      doc: stub,
      libraryRoot,
      initialPage: page ?? undefined,
      initialBbox: bbox
        ? [bbox.x0, bbox.y0, bbox.x1, bbox.y1]
        : undefined,
      initialEvidenceId: evidenceId ?? undefined,
    })
    onClose()
  }

  if (!molecule) return null

  const title = molecule.name || molecule.mol_id

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={title}
      width="100%"
      maxWidth="100%"
      height="100%"
      maxHeight="100%"
      fullScreenOnMobile={false}
    >
      <MoleculeDetailPanel
        molecule={molecule}
        libraryRoot={libraryRoot}
        onSaved={onSaved}
        onOpenPdf={handleOpenPdf}
      />
    </Modal>
  )
}
