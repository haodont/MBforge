import { useTranslation } from 'react-i18next'
import PatentFactsTable from './PatentFactsTable'
import PatentResultStatus from './PatentResultStatus'
import { Badge, Button, InlineAlert, Panel } from '@/components/ui'
import type { PatentFactsArtifact } from '@/api/http/library'

interface Props {
  facts: PatentFactsArtifact | null
  loadError?: boolean
  onOpenEvidence: (evidenceId: string, page?: number | null) => void
}

/** The deterministic Patent result: publication status, the adopted
 * measurements and the notices extraction recorded. Deciding a reading belongs
 * to the review center, so this pane only reads facts and links to evidence. */
export default function PatentAnalysisPane({ facts, loadError, onOpenEvidence }: Props) {
  const { t } = useTranslation()
  if (loadError) return <InlineAlert tone="danger">{t('patentAnalysis.loadError')}</InlineAlert>
  if (!facts) return <p className="patent-analysis-empty">{t('patentAnalysis.noResult')}</p>

  const issues = facts.issues
  const measurements = facts.measurements

  return (
    <div className="patent-analysis-pane">
      <Panel title={t('patentAnalysis.summary')}>
        <div className="patent-analysis-status">
          <Badge tone={facts.analysis_status === 'fallback' ? 'warning' : facts.analysis_status === 'succeeded' ? 'success' : 'neutral'}>
            {t(`patentAnalysis.status.${facts.analysis_status ?? 'disabled'}`)}
          </Badge>
          <Badge tone="neutral">{t(`patentAnalysis.mode.${facts.extraction_mode ?? 'deterministic'}`)}</Badge>
        </div>
        <PatentResultStatus facts={facts} />
        <dl className="patent-analysis-counts">
          <div><dt>{t('patentAnalysis.issues')}</dt><dd>{issues.length}</dd></div>
        </dl>
        {issues.length > 0 && <p className="patent-analysis-meta">{t('patentAnalysis.issueHint')}</p>}
      </Panel>

      <Panel title={t('patentAnalysis.measurementsTitle', { count: measurements.length })} collapsible>
        <PatentFactsTable key={`${facts.run_id}:${facts.revision ?? 0}`} facts={facts} onOpenEvidence={onOpenEvidence} />
      </Panel>

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
      {measurements.length === 0 && issues.length === 0 && <p className="patent-analysis-empty">{t('patentAnalysis.noPendingItems')}</p>}
    </div>
  )
}
