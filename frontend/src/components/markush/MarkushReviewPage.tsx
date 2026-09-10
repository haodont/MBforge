/**
 * Markush review page — thin wrapper that reads the active library root
 * from app context, parses an optional :docId route segment, and mounts
 * the MarkushWorkspace shell.
 */

import { useParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { useAppContext } from '@/context/AppContext'
import MarkushWorkspace from './MarkushWorkspace'

export default function MarkushReviewPage() {
  const { libraryRoot } = useAppContext()
  const { docId } = useParams<{ docId?: string }>()
  const { t } = useTranslation()

  if (!libraryRoot) {
    return (
      <div
        style={{
          padding: 24,
          color: 'var(--text-muted)',
          fontSize: 13,
          textAlign: 'center',
        }}
      >
        {t('markush.review.noLibrary', '请先在设置中选择文献库。')}
      </div>
    )
  }

  return <MarkushWorkspace libraryRoot={libraryRoot} docId={docId ?? null} />
}