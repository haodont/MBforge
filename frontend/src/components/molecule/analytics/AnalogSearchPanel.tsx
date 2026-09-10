import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { showToast } from '@/hooks/useToast'
import { molFindAnalogsWithActivity } from '@/api/http/molecule'
import type { AnalogWithActivity } from '@/api/http/molecule'
import type { MoleculeRecord } from '@/types'
import { Card, Slider, Button, DataTable, Select } from '../../ui'
import { getUserFacingError } from '@/utils/errors'

export interface AnalogSearchPanelProps {
  molecules: MoleculeRecord[]
}

export default function AnalogSearchPanel({ molecules }: AnalogSearchPanelProps) {
  const { t } = useTranslation()
  const [selectedId, setSelectedId] = useState('')
  const [minSim, setMinSim] = useState(0.7)
  const [results, setResults] = useState<AnalogWithActivity[]>([])
  const [loading, setLoading] = useState(false)

  const handleSearch = async () => {
    if (!selectedId.trim()) return
    setLoading(true)
    try {
      const analogs = await molFindAnalogsWithActivity(selectedId.trim(), minSim)
      setResults(analogs)
      if (analogs.length === 0) showToast(t('analytics.analogs.noMatches'), 'info')
    } catch (e) {
      showToast(`${t('analytics.search.failed')}: ${getUserFacingError(e)}`, 'error')
    } finally {
      setLoading(false)
    }
  }

  const selectOptions = molecules.map((m) => ({
    value: m.mol_id,
    label: `${m.name || m.mol_id} (${m.esmiles.slice(0, 30)}…)`,
  }))

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      <Card>
        <div style={{ display: 'flex', gap: 12, alignItems: 'flex-end', flexWrap: 'wrap' }}>
          <div style={{ flex: 1, minWidth: 200 }}>
            <div style={{ fontSize: 12, fontWeight: 600, marginBottom: 6, color: 'var(--text-secondary)' }}>
              {t('analytics.analogs.referenceId')}
            </div>
            <Select
              value={selectedId}
              onChange={setSelectedId}
              options={selectOptions}
              placeholder={t('analytics.relations.selectMolecule')}
            />
          </div>
          <div style={{ width: 200 }}>
            <div style={{ fontSize: 12, fontWeight: 600, marginBottom: 6, color: 'var(--text-secondary)' }}>
              {t('analytics.analogs.minSimilarity', { value: minSim.toFixed(2) })}
            </div>
            <Slider min={0.3} max={0.99} step={0.05} value={minSim} onChange={(v) => setMinSim(v)} />
          </div>
          <Button variant="primary" size="sm" onClick={handleSearch} loading={loading}>
              {t('analytics.analogs.find')}
          </Button>
        </div>
      </Card>

      {results.length > 0 && (
        <DataTable
          columns={[
            { key: 'mol_id', title: t('analytics.moleculeId'), width: 160 },
            { key: 'name', title: t('analytics.name'), width: 140 },
            { key: 'similarity_score', title: t('analytics.similarity'), render: (row: AnalogWithActivity) => `${(row.similarity_score * 100).toFixed(1)}%` },
            { key: 'activity', title: t('analytics.activity'), render: (row: AnalogWithActivity) =>
              row.activity != null ? `${row.activity.toFixed(2)} ${row.units}` : '—'
            },
            { key: 'esmiles', title: 'E-SMILES', render: (row: AnalogWithActivity) => (
              <code style={{ fontSize: 11, wordBreak: 'break-all' }}>{row.esmiles}</code>
            )},
          ]}
          data={results}
        />
      )}
    </div>
  )
}
