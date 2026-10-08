import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { showToast } from '@/hooks/useToast'
import {
  useAssignCluster,
  useClusterMembers,
  useMoleculeClusters,
  useRemoveFromCluster,
} from '@/api/query/hooks/useMolecules'
import type { ClusterInfo } from '@/api/http/molecule_chem'
import type { MoleculeRecord } from '@/types'
import { Card, Button, SectionTitle, Input, Select, ConfirmDialog } from '../../ui'
import { getUserFacingError } from '@/utils/errors'

export interface ClusterPanelProps {
  molecules: MoleculeRecord[]
}

export default function ClusterPanel({ molecules }: ClusterPanelProps) {
  const { t } = useTranslation()
  const clustersQuery = useMoleculeClusters()
  const clusters: ClusterInfo[] = clustersQuery.data ?? []
  const loading = clustersQuery.isFetching
  const [selectedClusterId, setSelectedClusterId] = useState<string | null>(null)
  const membersQuery = useClusterMembers(selectedClusterId)
  const selectedCluster = membersQuery.data ?? null
  const assignCluster = useAssignCluster()
  const removeFromCluster = useRemoveFromCluster()
  const [assignMolId, setAssignMolId] = useState('')
  const [assignClusterId, setAssignClusterId] = useState('')
  const [confirmAssignOpen, setConfirmAssignOpen] = useState(false)
  const [pendingRemove, setPendingRemove] = useState<{ molId: string; clusterId: string } | null>(null)

  useEffect(() => {
    if (clustersQuery.isError) {
      showToast(`${t('analytics.clusters.loadFailed')}: ${getUserFacingError(clustersQuery.error)}`, 'error')
    }
  }, [clustersQuery.isError, clustersQuery.error, t])

  useEffect(() => {
    if (selectedClusterId && membersQuery.isError) {
      showToast(t('analytics.clusters.membersFailed'), 'error')
    }
  }, [selectedClusterId, membersQuery.isError, t])

  const loadClusters = () => {
    void clustersQuery.refetch()
  }

  const handleAssign = async () => {
    if (!assignMolId || !assignClusterId) return
    setConfirmAssignOpen(false)
    try {
      await assignCluster.mutateAsync({ molId: assignMolId, clusterId: assignClusterId })
      showToast(t('analytics.clusters.assigned'), 'success')
      setAssignMolId('')
      setAssignClusterId('')
    } catch (e) {
      showToast(`${t('analytics.clusters.assignFailed')}: ${getUserFacingError(e)}`, 'error')
    }
  }

  const handleRemove = async (molId: string, clusterId: string) => {
    setPendingRemove(null)
    try {
      await removeFromCluster.mutateAsync({ molId, clusterId })
      showToast(t('analytics.clusters.removed'), 'success')
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
            onClick={() => setSelectedClusterId(c.cluster_id)}
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
