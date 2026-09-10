import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { showToast } from '@/hooks/useToast'
import { getUserFacingError } from '@/utils/errors'
import { molSearchSubstructure } from '@/api/http/molecule'
import type { SubstructureMatch } from '@/api/http/molecule'
import { Card, Input, Slider, Button, DataTable } from '../../ui'

export default function SubstructureSearchPanel() {
  const { t } = useTranslation()
  const [query, setQuery] = useState('')
  const [threshold, setThreshold] = useState(0.3)
  const [results, setResults] = useState<SubstructureMatch[]>([])
  const [loading, setLoading] = useState(false)

  const handleSearch = async () => {
    if (!query.trim()) return
    setLoading(true)
    try {
      const matches = await molSearchSubstructure(query.trim(), threshold)
      setResults(matches)
      if (matches.length === 0) showToast(t('analytics.search.noMatches'), 'info')
    } catch (e) {
      showToast(`${t('analytics.search.failed')}: ${getUserFacingError(e)}`, 'error')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      <Card>
        <div style={{ display: 'flex', gap: 12, alignItems: 'flex-end', flexWrap: 'wrap' }}>
          <div style={{ flex: 1, minWidth: 240 }}>
            <div style={{ fontSize: 12, fontWeight: 600, marginBottom: 6, color: 'var(--text-secondary)' }}>
              {t('analytics.substructure.queryLabel')}
            </div>
            <Input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder={t('analytics.substructure.placeholder')}
            />
          </div>
          <div style={{ width: 200 }}>
            <div style={{ fontSize: 12, fontWeight: 600, marginBottom: 6, color: 'var(--text-secondary)' }}>
              {t('analytics.substructure.threshold', { value: threshold.toFixed(2) })}
            </div>
            <Slider min={0.1} max={0.9} step={0.05} value={threshold} onChange={(v) => setThreshold(v)} />
          </div>
          <Button variant="primary" size="sm" onClick={handleSearch} loading={loading}>
            {t('common.search')}
          </Button>
        </div>
      </Card>

      {results.length > 0 && (
        <DataTable
          columns={[
            { key: 'mol_id', title: t('analytics.moleculeId'), width: 200 },
            { key: 'esmiles', title: 'E-SMILES', render: (row: SubstructureMatch) => (
              <code style={{ fontSize: 11, wordBreak: 'break-all' }}>{row.esmiles}</code>
            )},
          ]}
          data={results}
        />
      )}
    </div>
  )
}
