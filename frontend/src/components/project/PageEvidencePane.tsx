import { useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { useDocumentEvidence } from '@/api/query/hooks'
import type { DocumentEvidenceItem } from '@/api/http/library'
import Badge from '@/components/ui/Badge'
import { Panel } from '@/components/ui/Panel'
import Spinner from '@/components/ui/Spinner'

interface PageEvidencePaneProps {
  docId: string
  page: number
  libraryRoot: string
  selectedEvidenceId?: string | null
}

function panelTitle(title: string, count: number) {
  return (
    <div className="pdf-evidence-panel-title">
      <span>{title}</span>
      <Badge tone="neutral">{count}</Badge>
    </div>
  )
}

function evidenceContent(item: DocumentEvidenceItem, fallback: string): string {
  return item.raw_text.trim() ? item.raw_text : item.coref || fallback
}

export default function PageEvidencePane({ docId, page, libraryRoot, selectedEvidenceId }: PageEvidencePaneProps) {
  const { t } = useTranslation()
  const { data, isLoading } = useDocumentEvidence(docId, page, libraryRoot)
  const items = data?.ok ? data.data : null
  const error = data && !data.ok ? data.error : null

  useEffect(() => {
    if (!selectedEvidenceId || !items) return
    document.getElementById(`pdf-evidence-${selectedEvidenceId}`)?.scrollIntoView({ block: 'nearest' })
  }, [items, selectedEvidenceId])

  if (isLoading || (!items && !error)) {
    return (
      <div className="pdf-evidence-state">
        <Spinner />
        <span>{t('pdf.evidenceLoading')}</span>
      </div>
    )
  }
  if (error) {
    return <div className="pdf-evidence-state pdf-evidence-state--error">{error}</div>
  }
  if (!items) return null

  return (
    <div className="pdf-evidence-pane">
      <div className="pdf-evidence-source">
        <span>{t('pdf.evidenceSource')}</span>
        <Badge tone="info">{t('pdf.evidencePage', { page })}</Badge>
      </div>
      <Panel
        title={panelTitle(t('pdf.evidenceTitle'), items.length)}
        className="pdf-evidence-panel"
      >
        {items.length === 0 ? (
          <div className="pdf-evidence-empty">{t('pdf.evidenceEmpty')}</div>
        ) : (
          <div className="pdf-evidence-list">
            {items.map((item) => (
              <article
                id={`pdf-evidence-${item.evidence_id}`}
                className={`pdf-evidence-item${item.evidence_id === selectedEvidenceId ? ' is-selected' : ''}`}
                aria-current={item.evidence_id === selectedEvidenceId ? 'true' : undefined}
                key={item.evidence_id}
              >
                <div className="pdf-evidence-item__topline">
                  <Badge tone={item.kind === 'text_span' ? 'neutral' : 'info'}>
                    {item.kind}
                  </Badge>
                  <code>{item.evidence_id}</code>
                </div>
                <p>{evidenceContent(item, t('pdf.evidenceNoRawText'))}</p>
              </article>
            ))}
          </div>
        )}
      </Panel>
    </div>
  )
}
