import { useTranslation } from 'react-i18next'
import { InlineAlert } from '@/components/ui'
import type { PatentFactsArtifact } from '@/api/http/library'

export default function PatentResultStatus({ facts, detailed = false }: { facts: PatentFactsArtifact; detailed?: boolean }) {
  const { t } = useTranslation()
  const coverage = facts.coverage
  return <>
    <InlineAlert tone={facts.projection_status === 'pending' ? 'warning' : 'info'}>
      {t('patentAnalysis.projection.' + (facts.projection_status ?? 'unknown'))}
    </InlineAlert>
    <p className="patent-analysis-meta">{coverage
      ? t('patentAnalysis.coverageSummary', { complete: coverage.complete_evidence, partial: coverage.partial_evidence, total: coverage.total_evidence })
      : t('patentAnalysis.coverageUnknown')}</p>
    {detailed && coverage && <>
      <p className="patent-analysis-meta">{t('patentAnalysis.coverageHint')}</p>
      <dl className="patent-analysis-counts">
        {(['complete_pages', 'partial_pages', 'unread_pages', 'no_evidence_pages'] as const).map(key => <div key={key}>
          <dt>{t('patentAnalysis.coverage.' + key)}</dt><dd>{coverage[key].join(', ') || '—'}</dd>
        </div>)}
      </dl>
    </>}
  </>
}
