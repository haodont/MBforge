import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useReviewDecide, useReviewQueue } from '@/api/query/hooks/useReview'
import type { PatentFactReviewPayload, ReviewAction, ReviewQueueItem } from '@/api/http/review'
import type { PatentFactChoice } from '@/components/review/PatentFactReview'
import PatentFactReview from '@/components/review/PatentFactReview'
import PatentFactsTable from './PatentFactsTable'
import PatentResultStatus from './PatentResultStatus'
import { Badge, Button, InlineAlert, Panel } from '@/components/ui'
import type { PatentFactsArtifact } from '@/api/http/library'
import { getUserFacingError } from '@/utils/errors'

interface Props {
  docId: string
  libraryRoot: string
  facts: PatentFactsArtifact | null
  loadError?: boolean
  onOpenEvidence: (evidenceId: string, page?: number | null) => void
}

export default function PatentAnalysisPane({ docId, libraryRoot, facts, loadError, onOpenEvidence }: Props) {
  const { t } = useTranslation()
  const reviews = useReviewQueue(libraryRoot, { kind: 'patent_fact_review', status: 'pending', docId, pageSize: 100 })
  const decide = useReviewDecide()
  const [decisionError, setDecisionError] = useState('')
  if (loadError) return <InlineAlert tone="danger">{t('patentAnalysis.loadError')}</InlineAlert>
  if (!facts) return <p className="patent-analysis-empty">{t('patentAnalysis.noResult')}</p>

  const conflicts = facts.conflicts ?? []
  const reviewItems = reviews.data?.items ?? []
  const issues = facts.issues
  const llmErrorKey = 'patentAnalysis.error.' + (facts.llm?.error_code ?? 'unknown')
  const fallbackReason = t(llmErrorKey, { defaultValue: t('patentAnalysis.error.unknown') })

  const submitDecision = async (item: ReviewQueueItem, action: ReviewAction, choice?: PatentFactChoice) => {
    const payload = item.payload as PatentFactReviewPayload
    if (typeof payload.revision !== 'number') {
      setDecisionError(t('review.patentFact.unavailable'))
      return
    }
    try {
      const result = await decide.mutateAsync({
        libraryRoot,
        items: [{
          kind: 'patent_fact_review',
          id: item.id,
          expected_revision: payload.revision,
          ...(choice ? { choice } : {}),
        }],
        action,
      })
      setDecisionError(result.skipped > 0 ? t('review.patentFact.stale') : '')
      if (result.skipped > 0) void reviews.refetch()
    } catch (error) {
      setDecisionError(getUserFacingError(error, t('common.unknownError')))
    }
  }

  return (
    <div className="patent-analysis-pane">
      <Panel title={t('patentAnalysis.summary')}>
        <div className="patent-analysis-status">
          <Badge tone={facts.analysis_status === 'fallback' ? 'warning' : facts.analysis_status === 'succeeded' ? 'success' : 'neutral'}>
            {t(`patentAnalysis.status.${facts.analysis_status ?? 'disabled'}`)}
          </Badge>
          <Badge tone="neutral">{t(`patentAnalysis.mode.${facts.extraction_mode ?? 'deterministic'}`)}</Badge>
        </div>
        <PatentResultStatus facts={facts} detailed />
        <dl className="patent-analysis-counts">
          <div><dt>{t('patentAnalysis.conflicts')}</dt><dd>{conflicts.length}</dd></div>
          <div><dt>{t('patentAnalysis.candidates')}</dt><dd>{reviews.data?.total ?? facts.review_candidates?.length ?? 0}</dd></div>
          <div><dt>{t('patentAnalysis.issues')}</dt><dd>{issues.length}</dd></div>
        </dl>
        {facts.analysis_status === 'fallback' && (
          <InlineAlert tone="warning">
            {t('patentAnalysis.fallback', { reason: fallbackReason })}
          </InlineAlert>
        )}
        {facts.analysis_status === 'succeeded' && facts.extraction_mode === 'hybrid' && (
          <p className="patent-analysis-meta">
            {t('patentAnalysis.runMeta', {
              turns: facts.llm?.turns ?? '—',
              tokens: facts.llm?.tokens ?? t('patentAnalysis.unknown'),
            })}
          </p>
        )}
        {issues.length > 0 && <p className="patent-analysis-meta">{t('patentAnalysis.issueHint')}</p>}
      </Panel>

      <Panel title={t('patentAnalysis.measurementsTitle', { count: facts.measurements.length })} collapsible>
        <PatentFactsTable key={`${facts.run_id}:${facts.revision ?? 0}`} facts={facts} onOpenEvidence={onOpenEvidence} />
      </Panel>

      {((reviews.data?.total ?? facts.review_candidates?.length ?? 0) > 0 || reviews.isPending || reviews.isError) ? (
        <Panel title={t('patentAnalysis.reviewTitle', { count: reviews.data?.total ?? facts.review_candidates?.length ?? 0 })}>
          {decisionError && <InlineAlert tone="danger">{decisionError}</InlineAlert>}
          {reviews.isPending ? <p className="patent-analysis-meta">{t('common.loading')}</p>
            : reviews.isError ? <InlineAlert tone="danger">{t('patentAnalysis.reviewLoadError')} <Button size="sm" onClick={() => void reviews.refetch()}>{t('common.retry')}</Button></InlineAlert>
              : reviewItems.length === 0 ? <p className="patent-analysis-meta">{t('patentAnalysis.noPendingItems')}</p>
                : <div className="patent-analysis-candidate-list">
                  {reviewItems.map(item => (
                    <PatentFactReview
                      key={item.id}
                      item={item}
                      busy={decide.isPending}
                      onChoose={choice => void submitDecision(item, 'confirm', choice)}
                      onReopen={() => void submitDecision(item, 'reopen')}
                      onOpenEvidence={onOpenEvidence}
                    />
                  ))}
                </div>
          }
        </Panel>
      ) : null}

      {issues.length > 0 ? (
        <Panel title={t('patentAnalysis.issuesTitle', { count: issues.length })}>
          <ul className="patent-analysis-issues">
            {issues.slice(0, 5).map((issue, index) => (
              <li key={`${issue.code ?? 'issue'}-${index}`}>
                <Badge tone={issue.severity === 'error' ? 'danger' : 'warning'}>
                  {issue.severity || t('patentAnalysis.issue')}
                </Badge>
                <span>{issue.message || issue.code || t('patentAnalysis.issue')}</span>
                {issue.evidence_ids?.slice(0, 2).map(evidenceId => (
                  <Button key={evidenceId} variant="ghost" size="sm" onClick={() => onOpenEvidence(evidenceId)}>
                    {t('patentAnalysis.openEvidence')}
                  </Button>
                ))}
              </li>
            ))}
          </ul>
        </Panel>
      ) : null}
      {reviewItems.length === 0 && issues.length === 0 && <p className="patent-analysis-empty">{t('patentAnalysis.noPendingItems')}</p>}
    </div>
  )
}
