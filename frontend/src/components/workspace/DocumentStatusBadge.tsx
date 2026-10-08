/** Document status badge — resting status or live queue status + progress. */

import { useTranslation } from 'react-i18next'
import Badge from '@/components/ui/Badge'

/** Workspace status badge presentation, keyed by the status we display. */
const DOC_STATUS_META: Record<
  string,
  { tone: 'success' | 'warning' | 'danger' | 'info' | 'neutral'; cls: string; labelKey: string }
> = {
  pending: { tone: 'warning', cls: 'badge-pending', labelKey: 'workspace.statusPending' },
  processing: { tone: 'info', cls: 'badge-processing', labelKey: 'workspace.statusProcessing' },
  ready: { tone: 'success', cls: 'badge-ready', labelKey: 'workspace.statusReady' },
  error: { tone: 'danger', cls: 'badge-error', labelKey: 'workspace.statusError' },
  extracted: { tone: 'neutral', cls: 'badge-extracted', labelKey: 'workspace.statusExtracted' },
}

export interface DocumentStatusBadgeProps {
  /** Display status — a live queue status or the document's resting status. */
  status: string
  /** Stage completion percent while processing, else null. */
  progress: number | null
}

export default function DocumentStatusBadge({ status, progress }: DocumentStatusBadgeProps) {
  const { t } = useTranslation()
  const meta = DOC_STATUS_META[status] ?? DOC_STATUS_META.pending
  return (
    <span className="doc-status">
      <Badge tone={meta.tone} className={`doc-status-badge ${meta.cls}`}>
        {t(meta.labelKey)}
      </Badge>
      {progress !== null && (
        <span
          className="doc-status-progress"
          aria-label={t('workspace.processingProgress', { percent: progress })}
        >
          <span className="doc-status-progress__bar" aria-hidden>
            <span
              className="doc-status-progress__fill"
              style={{ width: `${progress}%` }}
            />
          </span>
          {progress}%
        </span>
      )}
    </span>
  )
}
