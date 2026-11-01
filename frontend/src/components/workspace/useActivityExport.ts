import { useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { exportStructureActivity } from '@/api/http/library'
import { showToast } from '@/hooks/useToast'
import { getUserFacingError } from '@/utils/errors'

export function useActivityExport(libraryRoot: string) {
  const { t } = useTranslation()
  const [exportPending, setExportPending] = useState(false)
  const inProgress = useRef(false)

  const handleExport = async (docIds: string[]) => {
    if (!libraryRoot || docIds.length === 0 || inProgress.current) return
    inProgress.current = true
    setExportPending(true)
    try {
      await exportStructureActivity(docIds, libraryRoot)
      showToast(t('workspace.activityExportSuccess'), 'success')
    } catch (error) {
      showToast(t('workspace.activityExportError', {
        error: getUserFacingError(error, t('common.unknownError')),
      }), 'error')
    } finally {
      inProgress.current = false
      setExportPending(false)
    }
  }

  return { exportPending, handleExport }
}
