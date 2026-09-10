import Button from '@/components/ui/Button'
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

function CloseIcon({ size = 18 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
      <line x1="18" y1="6" x2="6" y2="18" />
      <line x1="6" y1="6" x2="18" y2="18" />
    </svg>
  )
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
    })
    onClose()
  }

  if (!open || !molecule) return null

  const title = molecule.name || molecule.mol_id

  return (
    <>
      <div
        style={{
          position: 'fixed',
          inset: 0,
          background: 'rgba(0, 0, 0, 0.35)',
          zIndex: 40,
        }}
        onClick={onClose}
        aria-hidden="true"
      />
      <div
        style={{
          position: 'fixed',
          top: 0,
          right: 0,
          bottom: 0,
          width: '100vw',
          maxWidth: '100vw',
          background: 'var(--bg-surface)',
          borderLeft: '1px solid var(--border)',
          zIndex: 50,
          display: 'flex',
          flexDirection: 'column',
          boxShadow: '-4px 0 24px rgba(0, 0, 0, 0.15)',
        }}
        role="dialog"
        aria-modal="true"
        aria-label={title}
      >
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            padding: '14px 16px',
            borderBottom: '1px solid var(--border)',
          }}
        >
          <h3
            style={{
              margin: 0,
              fontSize: 15,
              fontWeight: 600,
              color: 'var(--text-primary)',
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              whiteSpace: 'nowrap',
            }}
            title={title}
          >
            {title}
          </h3>
          <Button
            variant="ghost"
            size="sm"
            onClick={onClose}
            icon={<CloseIcon size={18} />}
            aria-label="关闭"
          />
        </div>

        <div
          style={{
            flex: 1,
            minHeight: 0,
            overflow: 'hidden',
            padding: '16px',
            display: 'flex',
          }}
        >
          <MoleculeDetailPanel
            molecule={molecule}
            libraryRoot={libraryRoot}
            onSaved={onSaved}
            onOpenPdf={handleOpenPdf}
          />
        </div>
      </div>
    </>
  )
}
