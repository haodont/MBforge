/** Per-document actions: export activity and delete. */

import { useTranslation } from 'react-i18next'
import { useAppContext } from '@/context/AppContext'
import { DownloadIcon, TrashIcon } from '@/components/icons'
import Menu, { type MenuItem } from '@/components/ui/Menu'
import IconButton from '@/components/ui/IconButton'
import type { DocumentInfo } from '@/api/http/library'
import { useActivityExport } from './useActivityExport'

export interface DocumentActionMenuProps {
  doc: DocumentInfo
  deletePending: boolean
  onDelete: (doc: DocumentInfo) => void
}

export default function DocumentActionMenu({
  doc,
  deletePending,
  onDelete,
}: DocumentActionMenuProps) {
  const { t } = useTranslation()
  const { libraryRoot } = useAppContext()
  const { exportPending, handleExport } = useActivityExport(libraryRoot)

  const items: MenuItem[] = [
    {
      key: 'activity-export',
      label: exportPending ? t('workspace.activityExportPending') : t('doc.activityExport'),
      icon: <DownloadIcon size={16} />,
      disabled: exportPending || deletePending || !libraryRoot,
      onClick: () => handleExport([doc.doc_id]),
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
