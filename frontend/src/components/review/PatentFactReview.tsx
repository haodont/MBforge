import { useTranslation } from 'react-i18next'
import type { PatentFactReviewPayload, ReviewQueueItem } from '@/api/http/review'
import { Badge, Button, InlineAlert } from '@/components/ui'
import './PatentFactReview.css'

export type PatentFactChoice = 'deterministic' | 'llm' | 'neither'

interface Props {
  item: ReviewQueueItem
  busy?: boolean
  error?: string
  onChoose: (choice: PatentFactChoice, revision: number) => void
  onReopen: (revision: number) => void
  onOpenEvidence: (evidenceId: string, page: number | null) => void
}

function displayValue(value: unknown): string {
  return typeof value === 'string' || typeof value === 'number' ? String(value) : ''
}

function candidateRows(fields: Record<string, unknown> & { value_text?: string; raw_text?: string }) {
  const value = [
    displayValue(fields.comparator),
    displayValue(fields.value_text ?? fields.raw_text),
    displayValue(fields.unit),
  ].filter(Boolean).join(' ')
  return [
    ['metric', displayValue(fields.metric)],
    ['value', value],
    ['target', displayValue(fields.target)],
    ['system', displayValue(fields.system)],
    ['endpoint', displayValue(fields.endpoint ?? fields.assay_type)],
  ].filter((row): row is [string, string] => Boolean(row[1]))
}

export default function PatentFactReview({
  item,
  busy = false,
  error,
  onChoose,
  onReopen,
  onOpenEvidence,
}: Props) {
  const { t } = useTranslation()
  const payload = item.payload as PatentFactReviewPayload
  const revision = typeof payload.revision === 'number' ? payload.revision : null
  const candidates = payload.conflict?.candidates ?? []
  const sources = [...new Set(candidates.map(candidate => candidate.source))]

  return (
    <article className="patent-fact-review" aria-label={t('review.patentFact.detail')}>
      <header className="patent-fact-review__header">
        <Badge tone={item.status === 'pending' ? 'warning' : 'neutral'}>{t('review.status.' + item.status)}</Badge>
        <span>{t('review.patentFact.revision', { revision: revision ?? '—' })}</span>
      </header>
      {!revision || candidates.length === 0
        ? <InlineAlert tone="warning">{t('review.patentFact.unavailable')}</InlineAlert>
        : (
          <div className="patent-fact-review__candidates">
            {candidates.map((candidate, index) => (
              <section className="patent-fact-review__candidate" key={candidate.signature || candidate.source + '-' + String(index)}>
                <h3>{t('patentAnalysis.source.' + candidate.source)}</h3>
                <dl>
                  {candidateRows(candidate.fields).map(([field, value]) => (
                    <div key={field}>
                      <dt>{t('review.patentFact.field.' + field)}</dt>
                      <dd>{value}</dd>
                    </div>
                  ))}
                </dl>
                {candidate.evidence_ids.map(evidenceId => (
                  <Button key={evidenceId} size="sm" variant="ghost" onClick={() => onOpenEvidence(evidenceId, payload.conflict?.page ?? item.page)}>
                    {t('review.openSource')}
                  </Button>
                ))}
              </section>
            ))}
          </div>
        )}
      {error && <InlineAlert tone="danger">{error}</InlineAlert>}
      <div className="patent-fact-review__actions">
        {item.status === 'pending' ? (
          <>
            {sources.map(source => (
              <Button key={source} size="sm" disabled={busy || !revision} onClick={() => revision && onChoose(source, revision)}>
                {t('review.patentFact.choose.' + source)}
              </Button>
            ))}
            <Button size="sm" variant="secondary" disabled={busy || !revision || candidates.length === 0} onClick={() => revision && onChoose('neither', revision)}>
              {t('review.patentFact.choose.neither')}
            </Button>
          </>
        ) : (
          <Button size="sm" variant="ghost" disabled={busy || !revision} onClick={() => revision && onReopen(revision)}>
            {t('review.reopen')}
          </Button>
        )}
      </div>
    </article>
  )
}
