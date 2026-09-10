import { useState, useEffect, useCallback } from 'react'
import { useTranslation } from 'react-i18next'
import { showToast } from '@/hooks/useToast'
import {
  molListClusters,
  molGetClusterMembers,
  molAssignCluster,
  molRemoveFromCluster,
} from '@/api/http/molecule'
import type { ClusterInfo } from '@/api/http/molecule'
import type { MoleculeRecord } from '@/types'
import { Card, Button, SectionTitle, Input, Select, ConfirmDialog } from '../../ui'
import { getUserFacingError } from '@/utils/errors'

export interface ClusterPanelProps {
  molecules: MoleculeRecord[]
}

export default function ClusterPanel({ molecules }: ClusterPanelProps) {
  const { t } = useTranslation()
  const [clusters, setClusters] = useState<ClusterInfo[]>([])
  const [selectedCluster, setSelectedCluster] = useState<ClusterInfo | null>(null)
  const [loading, setLoading] = useState(false)
  const [assignMolId, setAssignMolId] = useState('')
  const [assignClusterId, setAssignClusterId] = useState('')
  const [confirmAssignOpen, setConfirmAssignOpen] = useState(false)
  const [pendingRemove, setPendingRemove] = useState<{ molId: string; clusterId: string } | null>(null)

  const loadClusters = useCallback(async () => {
    setLoading(true)
    try {
      const list = await molListClusters()
      setClusters(list)
    } catch (e) {
      showToast(`${t('analytics.clusters.loadFailed')}: ${getUserFacingError(e)}`, 'error')
    } finally {
      setLoading(false)
    }
  }, [t])

  useEffect(() => {
    void loadClusters()
  }, [loadClusters])

  const handleAssign = async () => {
    if (!assignMolId || !assignClusterId) return
    setConfirmAssignOpen(false)
    try {
      await molAssignCluster(assignMolId, assignClusterId)
      showToast(t('analytics.clusters.assigned'), 'success')
      void loadClusters()
      setAssignMolId('')
      setAssignClusterId('')
    } catch (e) {
      showToast(`${t('analytics.clusters.assignFailed')}: ${getUserFacingError(e)}`, 'error')
    }
  }

  const handleRemove = async (molId: string, clusterId: string) => {
    setPendingRemove(null)
    try {
      await molRemoveFromCluster(molId, clusterId)
      showToast(t('analytics.clusters.removed'), 'success')
      void loadClusters()
      if (selectedCluster?.cluster_id === clusterId) {
        const updated = await molGetClusterMembers(clusterId)
        setSelectedCluster(updated)
      }
    } catch (e) {
      showToast(`${t('analytics.clusters.removeFailed')}: ${getUserFacingError(e)}`, 'error')
    }
  }

  const molOptions = molecules.map((m) => ({
    value: m.mol_id,
    label: m.name || m.mol_id,
  }))

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      <Card>
        <div style={{ display: 'flex', gap: 12, alignItems: 'flex-end', flexWrap: 'wrap' }}>
          <div style={{ flex: 1, minWidth: 200 }}>
            <div style={{ fontSize: 12, fontWeight: 600, marginBottom: 6, color: 'var(--text-secondary)' }}>
              {t('analytics.moleculeId')}
            </div>
            <Select
              value={assignMolId}
              onChange={setAssignMolId}
              options={molOptions}
              placeholder={t('analytics.relations.selectMolecule')}
            />
          </div>
          <div style={{ flex: 1, minWidth: 200 }}>
            <div style={{ fontSize: 12, fontWeight: 600, marginBottom: 6, color: 'var(--text-secondary)' }}>
              {t('analytics.clusters.clusterId')}
            </div>
            <Input value={assignClusterId} onChange={(e) => setAssignClusterId(e.target.value)} placeholder={t('analytics.clusters.clusterPlaceholder')} />
          </div>
          <Button variant="primary" size="sm" onClick={() => setConfirmAssignOpen(true)}>
            {t('analytics.clusters.assign')}
          </Button>
          <Button variant="secondary" size="sm" onClick={loadClusters} loading={loading}>
            {t('common.refresh')}
          </Button>
        </div>
      </Card>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(260px, 1fr))', gap: 12 }}>
        {clusters.map((c) => (
          <Card
            key={c.cluster_id}
            hoverable
            onClick={async () => {
              try {
                const info = await molGetClusterMembers(c.cluster_id)
                setSelectedCluster(info)
              } catch {
                showToast(t('analytics.clusters.membersFailed'), 'error')
              }
            }}
          >
            <div style={{ fontWeight: 600, fontSize: 14, marginBottom: 4 }}>{c.cluster_id}</div>
            <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>{t('analytics.clusters.members', { count: c.member_count })}</div>
          </Card>
        ))}
      </div>

      {selectedCluster && (
        <Card>
          <SectionTitle>{t('analytics.clusters.selected', { id: selectedCluster.cluster_id, count: selectedCluster.members.length })}</SectionTitle>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginTop: 8 }}>
            {selectedCluster.members.map((molId) => (
              <div
                key={molId}
                style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                  padding: '6px 8px',
                  background: 'var(--bg-base)',
                  borderRadius: 4,
                }}
              >
                <code style={{ fontSize: 12 }}>{molId}</code>
                <Button
                  variant="danger"
                  size="sm"
                  onClick={() => setPendingRemove({ molId, clusterId: selectedCluster.cluster_id })}
                >
                  {t('common.remove')}
                </Button>
              </div>
            ))}
          </div>
        </Card>
      )}

      <ConfirmDialog
        open={confirmAssignOpen}
        title={t('analytics.clusters.assign')}
        message={t('analytics.clusters.assignConfirm')}
        confirmLabel={t('analytics.clusters.assign')}
        onConfirm={() => void handleAssign()}
        onCancel={() => setConfirmAssignOpen(false)}
      />
      <ConfirmDialog
        open={pendingRemove !== null}
        title={t('common.remove')}
        message={t('analytics.clusters.removeConfirm')}
        confirmLabel={t('common.remove')}
        onConfirm={() => { if (pendingRemove) void handleRemove(pendingRemove.molId, pendingRemove.clusterId) }}
        onCancel={() => setPendingRemove(null)}
      />
    </div>
  )
}
