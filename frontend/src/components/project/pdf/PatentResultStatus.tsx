import { useTranslation } from 'react-i18next'
import { InlineAlert } from '@/components/ui'
import type { PatentFactsArtifact } from '@/api/http/library'

/** Publication state of the committed snapshot, observed on read. */
export default function PatentResultStatus({ facts }: { facts: PatentFactsArtifact }) {
  const { t } = useTranslation()
  return (
    <InlineAlert tone={facts.projection_status === 'pending' ? 'warning' : 'info'}>
      {t('patentAnalysis.projection.' + (facts.projection_status ?? 'unknown'))}
    </InlineAlert>
  )
}
