import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { showToast } from '@/hooks/useToast'
import { getUserFacingError } from '@/utils/errors'
import { useSubstructureSearch } from '@/api/query/hooks/useMolecules'
import type { SubstructureMatch } from '@/api/http/molecule_chem'
import { Card, Input, Slider, Button, DataTable } from '../../ui'

export default function SubstructureSearchPanel() {
  const { t } = useTranslation()
  const [query, setQuery] = useState('')
  const [threshold, setThreshold] = useState(0.3)
  const [submitted, setSubmitted] = useState<{ query: string; threshold: number } | null>(null)

  const search = useSubstructureSearch(submitted?.query ?? null, submitted?.threshold ?? threshold)
  const results: SubstructureMatch[] = search.data ?? []
  const loading = search.isFetching

  const notifiedRef = useRef<string | null>(null)
  useEffect(() => {
    if (!submitted) return
    const key = `${submitted.query}::${submitted.threshold}`
    if (notifiedRef.current === key) return
    if (search.isError) {
      notifiedRef.current = key
      showToast(`${t('analytics.search.failed')}: ${getUserFacingError(search.error)}`, 'error')
    } else if (search.isSuccess) {
      notifiedRef.current = key
      if (results.length === 0) showToast(t('analytics.search.noMatches'), 'info')
    }
  }, [submitted, search.isError, search.isSuccess, search.error, results.length, t])

  const handleSearch = () => {
    const trimmed = query.trim()
    if (!trimmed) return
    setSubmitted({ query: trimmed, threshold })
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
