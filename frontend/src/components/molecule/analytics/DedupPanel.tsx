import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { showToast } from '@/hooks/useToast'
import { molDedupBatch } from '@/api/http/molecule'
import type { DedupResult } from '@/api/http/molecule'
import type { MoleculeRecord } from '@/types'
import { Card, Button, Slider, SectionTitle, AlertBanner, ResponsiveStatGrid, StatCard, DataTable, ConfirmDialog } from '../../ui'
import { getUserFacingError } from '@/utils/errors'

export interface DedupPanelProps {
  molecules: MoleculeRecord[]
  onComplete: () => void
}

export default function DedupPanel({ molecules, onComplete }: DedupPanelProps) {
  const { t } = useTranslation()
  const [threshold, setThreshold] = useState(0.95)
  const [result, setResult] = useState<DedupResult | null>(null)
  const [loading, setLoading] = useState(false)
  const [confirmOpen, setConfirmOpen] = useState(false)

  const runDedup = async () => {
    if (molecules.length === 0) {
      showToast(t('analytics.dedup.empty'), 'warning')
      return
    }
    setConfirmOpen(false)
    setLoading(true)
    try {
      const newMols: Array<[string, string]> = molecules.map((m) => [m.mol_id, m.esmiles])
      const res = await molDedupBatch(newMols, threshold)
      setResult(res)
      showToast(t('analytics.dedup.done', { count: res.duplicates.length }), 'success')
      onComplete()
    } catch (e) {
      showToast(`${t('analytics.dedup.failed')}: ${getUserFacingError(e)}`, 'error')
    } finally {
      setLoading(false)
    }
  }

  const handleDedup = () => {
    if (molecules.length === 0) {
      showToast(t('analytics.dedup.empty'), 'warning')
      return
    }
    setConfirmOpen(true)
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      <AlertBanner
        variant="info"
        message={t('analytics.dedup.description')}
      />

      <Card>
        <div style={{ display: 'flex', gap: 12, alignItems: 'flex-end', flexWrap: 'wrap' }}>
          <div style={{ width: 260 }}>
            <div style={{ fontSize: 12, fontWeight: 600, marginBottom: 6, color: 'var(--text-secondary)' }}>
              {t('analytics.dedup.threshold', { value: threshold.toFixed(2) })}
            </div>
            <Slider min={0.8} max={1.0} step={0.01} value={threshold} onChange={(v) => setThreshold(v)} />
          </div>
          <Button variant="primary" size="sm" onClick={handleDedup} loading={loading}>
            {t('analytics.dedup.run')}
          </Button>
        </div>
      </Card>

      {result && (
        <Card>
          <SectionTitle>{t('analytics.dedup.result')}</SectionTitle>
          <ResponsiveStatGrid style={{ marginTop: 12 }}>
            <StatCard label={t('analytics.dedup.duplicates')} value={result.duplicates.length} />
            <StatCard label={t('analytics.dedup.newMolecules')} value={result.new_mols.length} />
            <StatCard label={t('analytics.dedup.relationsAdded')} value={result.relations_added} />
          </ResponsiveStatGrid>

          {result.duplicates.length > 0 && (
            <div style={{ marginTop: 12 }}>
              <DataTable
                columns={[
                  { key: 'mol_a_id', title: t('analytics.moleculeA'), width: 160 },
                  { key: 'mol_b_id', title: t('analytics.moleculeB'), width: 160 },
                  { key: 'confidence', title: t('analytics.dedup.confidence'), render: (row) => `${(row.confidence * 100).toFixed(1)}%` },
                  { key: 'reason', title: t('analytics.dedup.reason') },
                ]}
                data={result.duplicates}
              />
            </div>
          )}
        </Card>
      )}

      <ConfirmDialog
        open={confirmOpen}
        title={t('analytics.dedup.run')}
        message={t('analytics.dedup.confirm')}
        confirmLabel={t('analytics.dedup.run')}
        loading={loading}
        onConfirm={() => void runDedup()}
        onCancel={() => setConfirmOpen(false)}
      />
    </div>
  )
}
