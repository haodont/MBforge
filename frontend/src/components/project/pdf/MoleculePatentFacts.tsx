import { useTranslation } from 'react-i18next'
import Badge from '@/components/ui/Badge'
import type { PatentFactsArtifact, PatentFactsMeasurement } from '@/api/http/library'
import type { ExtractionResult } from '@/types'

function compoundLabelKey(value: string): string {
  const cleaned = value
    .normalize('NFKC')
    .trim()
    .replace(/^(?:化合物|compound|cmpd|cpd|mol(?:ecule)?)[#_\-\s]*/i, '')
    .replace(/\s+/g, '')
  const match = /^(\d+[a-z]?)$/i.exec(cleaned)
  return (match?.[1] ?? cleaned).toLowerCase()
}

function measurementLabel(measurement: PatentFactsMeasurement): string {
  const value = measurement.value
  return `${measurement.metric || '—'} ${value.operator} ${value.raw_text} ${value.original_unit}`.trim()
}

export default function MoleculePatentFacts({
  facts,
  detection,
}: {
  facts: PatentFactsArtifact | null
  detection: ExtractionResult
}) {
  const { t } = useTranslation()
  if (!facts || !detection.name) return null
  const labelKey = compoundLabelKey(detection.name)
  const entries = facts.entries.filter((entry) => entry.label_key === labelKey)
  if (entries.length === 0) return null

  const entryIds = new Set(entries.map((entry) => entry.entry_id))
  const measurements = facts.measurements.filter(
    (measurement) => measurement.compound_entry_id && entryIds.has(measurement.compound_entry_id),
  )
  const evidenceIds = new Set([
    ...entries.flatMap((entry) => entry.evidence_ids),
    ...measurements.flatMap((measurement) => measurement.evidence_ids),
  ])

  return (
    <span className="pdf-current-molecule__facts">
      <span className="pdf-current-molecule__facts-header">
        <strong>{t('pdf.moleculeFactsTitle')}</strong>
        <Badge tone={measurements.length > 0 ? 'success' : 'neutral'}>
          {measurements.length > 0 ? t('pdf.patentFactsMeasured') : t('pdf.moleculeFactsNoMeasurement')}
        </Badge>
      </span>
      {entries.map((entry) => {
        const section = facts.sections.find((item) => item.section_id === entry.section_id)
        return (
          <span className="pdf-current-molecule__fact" key={entry.entry_id}>
            <span>{section?.title || entry.label_raw || entry.label_key}</span>
            {measurements
              .filter((measurement) => measurement.compound_entry_id === entry.entry_id)
              .map((measurement) => (
                <strong key={measurement.measurement_id}>{measurementLabel(measurement)}</strong>
              ))}
          </span>
        )
      })}
      <span className="pdf-current-molecule__facts-meta">
        {t('pdf.moleculeFactsEvidence', { count: evidenceIds.size })}
      </span>
    </span>
  )
}
