/** Per-document action menu — enqueue / patent analysis / delete. */

import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useAppContext } from '@/context/AppContext'
import { useEnqueueTask } from '@/api/query/hooks'
import { showToast } from '@/hooks/useToast'
import { FlaskIcon, FolderIcon, TrashIcon } from '@/components/icons'
import Menu, { type MenuItem } from '@/components/ui/Menu'
import IconButton from '@/components/ui/IconButton'
import type { DocumentInfo } from '@/api/http/library'
import { getUserFacingError } from '@/utils/errors'

export interface DocumentActionMenuProps {
  doc: DocumentInfo
  deletePending: boolean
  patentPending: boolean
  onDelete: (doc: DocumentInfo) => void
  onPatentAnalyze: (doc: DocumentInfo) => void
}

export default function DocumentActionMenu({
  doc,
  deletePending,
  patentPending,
  onDelete,
  onPatentAnalyze,
}: DocumentActionMenuProps) {
  const { t } = useTranslation()
  const { libraryRoot } = useAppContext()
  const enqueueMutation = useEnqueueTask()
  const [enqueuePending, setEnqueuePending] = useState(false)

  const handleEnqueue = async () => {
    if (!libraryRoot) return
    setEnqueuePending(true)
    try {
      // Backend resolves the file path from the document registry; only doc_id is needed.
      await enqueueMutation.mutateAsync({ libraryRoot, filePath: '', docId: doc.doc_id })
      showToast(t('doc.enqueueSuccess', { filename: doc.file_name }), 'success')
    } catch (e) {
      showToast(t('doc.enqueueFailed', { error: getUserFacingError(e, t('common.unknownError')) }), 'error')
    } finally {
      setEnqueuePending(false)
    }
  }

  const items: MenuItem[] = [
    {
      key: 'enqueue',
      label: t('doc.enqueue'),
      icon: <FolderIcon size={16} />,
      disabled: enqueuePending,
      onClick: handleEnqueue,
    },
    {
      key: 'patent-analysis',
      label: t('doc.patentAnalysis'),
      icon: <FlaskIcon size={16} />,
      disabled: patentPending,
      onClick: () => onPatentAnalyze(doc),
    },
    { type: 'separator', key: 'sep-delete' },
    {
      key: 'delete',
      label: t('doc.delete'),
      icon: <TrashIcon size={16} />,
      danger: true,
      disabled: deletePending,
      onClick: () => onDelete(doc),
    },
  ]

  return (
    <Menu
      align="right"
      items={items}
      trigger={(toggle) => (
        <IconButton
          size={32}
          ariaLabel={t('doc.actions')}
          title={t('doc.actions')}
          onClick={(event) => {
            event.stopPropagation()
            toggle()
          }}
        >
          ⋯
        </IconButton>
      )}
    />
  )
}
