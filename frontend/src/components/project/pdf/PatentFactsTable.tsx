import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Button, Modal } from '@/components/ui'
import DataTable, { type DataTableColumn } from '@/components/ui/DataTable'
import type { PatentFactsArtifact, PatentFactsAssayMethod, PatentFactsMeasurement } from '@/api/http/library'

type FactRow = { measurement: PatentFactsMeasurement; compound: string; method: PatentFactsAssayMethod | undefined; sources: string[] }

export default function PatentFactsTable({ facts, onOpenEvidence }: { facts: PatentFactsArtifact; onOpenEvidence: (id: string) => void }) {
  const { t } = useTranslation()
  const [assayId, setAssayId] = useState<string | null>(null)
  const [sources, setSources] = useState<string[] | null>(null)
  const assay = facts.assay_methods.find(method => method.assay_method_id === assayId)
  const rows: FactRow[] = facts.measurements.map(measurement => {
    const entry = facts.entries.find(item => item.entry_id === measurement.compound_entry_id)
    const method = facts.assay_methods.find(item => item.assay_method_id === measurement.assay_method_id)
    return { measurement, method, compound: entry?.label_raw || measurement.mol_id || t('patentAnalysis.unlinked'),
      sources: [...new Set([...measurement.evidence_ids, ...(method?.evidence_ids ?? []), ...(entry?.evidence_ids ?? [])])] }
  })
  const columns: DataTableColumn<FactRow>[] = [
    { key: 'compound', title: t('patentAnalysis.compound'), render: row => row.compound },
    { key: 'assay', title: t('patentAnalysis.assay'), render: row => <div className="patent-fact-cell">
      <strong>{row.measurement.metric || t('patentAnalysis.unknown')}</strong>
      {row.method ? <Button size="sm" variant="ghost" onClick={() => setAssayId(row.method?.assay_method_id ?? null)}>{[row.method.target, row.method.endpoint].filter(Boolean).join(' · ') || t('patentAnalysis.assayDetails')}</Button> : <span>{t('patentAnalysis.unknown')}</span>}
      {row.method?.system && <small>{row.method.system}</small>}
    </div> },
    { key: 'value', title: t('patentAnalysis.reportedValue'), render: row => <div className="patent-fact-cell">
      <span>{row.measurement.value.raw_text || row.measurement.value.qualitative_value || String(row.measurement.value.original_value ?? '—')}</span>
      <small>{t('patentAnalysis.valueDetails', { comparator: row.measurement.value.operator || '—', unit: row.measurement.value.original_unit || '—' })}</small>
    </div> },
    { key: 'sources', title: t('patentAnalysis.sources'), render: row => row.sources.length
      ? <Button size="sm" variant="ghost" onClick={() => setSources(row.sources)}>{t('patentAnalysis.sourceCount', { count: row.sources.length })}</Button> : t('patentAnalysis.noSource') },
  ]
  return <>
    <p className="patent-analysis-meta">{t('patentAnalysis.factUseHint')}</p>
    <DataTable columns={columns} data={rows} rowKey={row => row.measurement.measurement_id} size="sm" pagination={{ pageSize: 25, showTotal: true }} emptyText={t('patentAnalysis.noMeasurements')} />
    <Modal open={assay !== undefined} onClose={() => setAssayId(null)} title={t('patentAnalysis.assayDetails')} maxWidth={720}>
      {assay && <div className="patent-assay-details">
        <p>{assay.raw_text || t('patentAnalysis.unknown')}</p>
        <dl>{Object.entries({ target: assay.target, system: assay.system, endpoint: assay.endpoint, ...assay.conditions } as Record<string, unknown>).map(([key, value]) => <div key={key}>
          <dt>{key}</dt><dd>{value === null || value === undefined ? '—' : typeof value === 'string' ? value : JSON.stringify(value)}</dd>
        </div>)}</dl>
        {assay.evidence_ids.map(id => <Button key={id} size="sm" variant="ghost" onClick={() => { setAssayId(null); onOpenEvidence(id) }}>{t('patentAnalysis.openEvidence')}</Button>)}
      </div>}
    </Modal>
    <Modal open={sources !== null} onClose={() => setSources(null)} title={t('patentAnalysis.sources')} maxWidth={600}>
      <p>{t('patentAnalysis.sourceHint')}</p>
      <div className="patent-source-list">{sources?.map((id, index) => <Button key={id} variant="ghost" onClick={() => { setSources(null); onOpenEvidence(id) }}>
        {t('patentAnalysis.sourceNumber', { number: index + 1 })}<small>{id}</small>
      </Button>)}</div>
    </Modal>
  </>
}
