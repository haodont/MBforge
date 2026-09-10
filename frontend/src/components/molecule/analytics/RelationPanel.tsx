import { useState, useEffect, useCallback } from 'react'
import { useTranslation } from 'react-i18next'
import { showToast } from '@/hooks/useToast'
import {
  molGetStats,
  molFindByMolecule,
  molAddRelation,
  molDeleteRelation,
} from '@/api/http/molecule'
import type { RelationStats, MoleculeRelation } from '@/api/http/molecule'
import type { MoleculeRecord } from '@/types'
import { Card, Button, SectionTitle, Input, DataTable, Select, ResponsiveStatGrid, StatCard, ConfirmDialog } from '../../ui'
import { getUserFacingError } from '@/utils/errors'

export interface RelationPanelProps {
  molecules: MoleculeRecord[]
}

export default function RelationPanel({ molecules }: RelationPanelProps) {
  const { t } = useTranslation()
  const [stats, setStats] = useState<RelationStats | null>(null)
  const [searchMolId, setSearchMolId] = useState('')
  const [relations, setRelations] = useState<MoleculeRelation[]>([])
  const [loading, setLoading] = useState(false)

  // 添加关系表单
  const [newRelA, setNewRelA] = useState('')
  const [newRelB, setNewRelB] = useState('')
  const [newRelType, setNewRelType] = useState<'similar' | 'same_as' | 'scaffold' | 'cluster'>('similar')
  const [newRelScore, setNewRelScore] = useState('')
  const [confirmAddOpen, setConfirmAddOpen] = useState(false)
  const [pendingDeleteId, setPendingDeleteId] = useState<number | null>(null)

  const loadStats = useCallback(async () => {
    try {
      const s = await molGetStats()
      setStats(s)
    } catch {
      showToast(t('analytics.relations.loadFailed'), 'error')
    }
  }, [t])

  useEffect(() => {
    void loadStats()
  }, [loadStats])

  const handleSearchRelations = async () => {
    if (!searchMolId.trim()) return
    setLoading(true)
    try {
      const list = await molFindByMolecule(searchMolId.trim())
      setRelations(list)
    } catch (e) {
      showToast(`${t('analytics.relations.searchFailed')}: ${getUserFacingError(e)}`, 'error')
    } finally {
      setLoading(false)
    }
  }

  const handleAddRelation = async () => {
    if (!newRelA || !newRelB) return
    setConfirmAddOpen(false)
    try {
      await molAddRelation(newRelA, newRelB, newRelType, newRelScore ? parseFloat(newRelScore) : undefined)
      showToast(t('analytics.relations.added'), 'success')
      void loadStats()
      setNewRelA('')
      setNewRelB('')
      setNewRelScore('')
    } catch (e) {
      showToast(`${t('analytics.relations.addFailed')}: ${getUserFacingError(e)}`, 'error')
    }
  }

  const handleDeleteRelation = async (id: number) => {
    setPendingDeleteId(null)
    try {
      await molDeleteRelation(id)
      showToast(t('analytics.relations.deleted'), 'success')
      setRelations((prev) => prev.filter((r) => r.id !== id))
      void loadStats()
    } catch (e) {
      showToast(`${t('analytics.relations.deleteFailed')}: ${getUserFacingError(e)}`, 'error')
    }
  }

  const molOptions = molecules.map((m) => ({
    value: m.mol_id,
    label: m.name || m.mol_id,
  }))

  const relTypeOptions = [
    { value: 'similar', label: t('analytics.relations.similar') },
    { value: 'same_as', label: t('analytics.relations.sameAs') },
    { value: 'scaffold', label: t('analytics.relations.scaffold') },
    { value: 'cluster', label: t('analytics.relations.cluster') },
  ]

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      {stats && (
        <ResponsiveStatGrid>
          <StatCard label={t('analytics.relations.total')} value={stats.total} />
          <StatCard label={t('analytics.relations.similar')} value={stats.similar} />
          <StatCard label={t('analytics.relations.sameAs')} value={stats.same_as} />
          <StatCard label={t('analytics.relations.scaffold')} value={stats.scaffold} />
          <StatCard label={t('analytics.relations.cluster')} value={stats.cluster} />
        </ResponsiveStatGrid>
      )}

      <Card>
        <SectionTitle>{t('analytics.relations.addTitle')}</SectionTitle>
        <div style={{ display: 'flex', gap: 12, alignItems: 'flex-end', flexWrap: 'wrap', marginTop: 8 }}>
          <div style={{ flex: 1, minWidth: 160 }}>
            <div style={{ fontSize: 12, fontWeight: 600, marginBottom: 6, color: 'var(--text-secondary)' }}>{t('analytics.moleculeA')}</div>
            <Select
              value={newRelA}
              onChange={setNewRelA}
              options={molOptions}
              placeholder={t('analytics.relations.select')}
            />
          </div>
          <div style={{ flex: 1, minWidth: 160 }}>
            <div style={{ fontSize: 12, fontWeight: 600, marginBottom: 6, color: 'var(--text-secondary)' }}>{t('analytics.moleculeB')}</div>
            <Select
              value={newRelB}
              onChange={setNewRelB}
              options={molOptions}
              placeholder={t('analytics.relations.select')}
            />
          </div>
          <div style={{ width: 140 }}>
            <div style={{ fontSize: 12, fontWeight: 600, marginBottom: 6, color: 'var(--text-secondary)' }}>{t('analytics.relations.type')}</div>
            <Select
              value={newRelType}
              onChange={(v) => setNewRelType(v as typeof newRelType)}
              options={relTypeOptions}
            />
          </div>
          <div style={{ width: 100 }}>
            <div style={{ fontSize: 12, fontWeight: 600, marginBottom: 6, color: 'var(--text-secondary)' }}>{t('analytics.relations.score')}</div>
            <Input value={newRelScore} onChange={(e) => setNewRelScore(e.target.value)} placeholder="0.0-1.0" />
          </div>
          <Button variant="primary" size="sm" onClick={() => setConfirmAddOpen(true)}>
            {t('common.add')}
          </Button>
        </div>
      </Card>

      <Card>
        <SectionTitle>{t('analytics.relations.searchTitle')}</SectionTitle>
        <div style={{ display: 'flex', gap: 12, alignItems: 'flex-end', marginTop: 8 }}>
          <div style={{ flex: 1 }}>
            <Select
              value={searchMolId}
              onChange={setSearchMolId}
              options={molOptions}
              placeholder={t('analytics.relations.select')}
            />
          </div>
          <Button variant="secondary" size="sm" onClick={handleSearchRelations} loading={loading}>
            {t('common.search')}
          </Button>
        </div>

        {relations.length > 0 && (
          <div style={{ marginTop: 12 }}>
            <DataTable
              columns={[
                { key: 'mol_a_id', title: t('analytics.moleculeA'), width: 140 },
                { key: 'mol_b_id', title: t('analytics.moleculeB'), width: 140 },
                { key: 'relation_type', title: t('analytics.relations.type'), width: 100 },
                { key: 'score', title: t('analytics.relations.score'), render: (row: MoleculeRelation) => row.score?.toFixed(3) ?? '—' },
                {
                  key: 'actions',
                  title: t('common.actions'),
                  render: (row: MoleculeRelation) => (
                    <Button
                      variant="danger"
                      size="sm"
                      onClick={() => row.id != null && setPendingDeleteId(row.id)}
                    >
                      {t('common.delete')}
                    </Button>
                  ),
                },
              ]}
              data={relations}
            />
          </div>
        )}
      </Card>

      <ConfirmDialog
        open={confirmAddOpen}
        title={t('common.add')}
        message={t('analytics.relations.addConfirm')}
        confirmLabel={t('common.add')}
        onConfirm={() => void handleAddRelation()}
        onCancel={() => setConfirmAddOpen(false)}
      />
      <ConfirmDialog
        open={pendingDeleteId !== null}
        title={t('common.delete')}
        message={t('analytics.relations.deleteConfirm')}
        confirmLabel={t('common.delete')}
        onConfirm={() => { if (pendingDeleteId !== null) void handleDeleteRelation(pendingDeleteId) }}
        onCancel={() => setPendingDeleteId(null)}
      />
    </div>
  )
}
