/**
 * Markush review workspace — three-column shell.
 *
 *  ┌────────────────┬──────────────────────┬──────────────────────┐
 *  │ Queue          │ Evidence             │ Review / edit panel  │
 *  │ (list of       │ (original crops +    │ (confirm_complete,   │
 *  │  pending       │  RDKit rendering     │  confirm_scaffold,   │
 *  │  candidates)   │  of editable SMILES) │  confirm_fragment,   │
 *  │                │                      │  reject, reopen, …)  │
 *  └────────────────┴──────────────────────┴──────────────────────┘
 *
 * All server state lives in React Query (``useMarkush*`` hooks); this
 * component is the orchestrator and owns the selected-candidate state.
 */

import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  useMarkushCandidates,
  useMarkushCandidate,
  useMarkushDecision,
  useMarkushUpdate,
} from '@/api/query/useMarkush'
import { showToast } from '@/components/ui/Toast'
import { getUserFacingError } from '@/utils/errors'
import MarkushQueue from './MarkushQueue'
import MarkushEvidencePane from './MarkushEvidencePane'
import MarkushReviewPanel from './MarkushReviewPanel'

interface MarkushWorkspaceProps {
  libraryRoot: string
  /** When set, lock the workspace to a single document. */
  docId?: string | null
}

export default function MarkushWorkspace({
  libraryRoot,
  docId,
}: MarkushWorkspaceProps) {
  const { t } = useTranslation()
  const [selectedCandidateId, setSelectedCandidateId] = useState<string | null>(null)
  const [filterStatus, setFilterStatus] = useState<string>('pending')

  const listFilters = {
    library_root: libraryRoot,
    doc_id: docId ?? null,
    review_status: filterStatus === 'all' ? null : (filterStatus as 'pending' | 'confirmed' | 'rejected'),
    page: 1,
    page_size: 100,
  }

  const list = useMarkushCandidates(listFilters)
  const detail = useMarkushCandidate(libraryRoot, selectedCandidateId)
  const decision = useMarkushDecision(libraryRoot)
  const update = useMarkushUpdate(libraryRoot)

  function handleDecision(action: 'confirm_complete' | 'confirm_scaffold' | 'confirm_fragment' | 'reject' | 'reopen') {
    const candidate = detail.data
    if (!candidate) return
    decision.mutate(
      {
        entityId: candidate.candidate_id,
        expectedVersion: candidate.review_version,
        action,
      },
      {
        onSuccess: () => {
          showToast(t('markush.toast.decisionApplied', '决策已应用'), 'success')
          setSelectedCandidateId(null)
        },
        onError: (err: unknown) => {
          showToast(getUserFacingError(err, t('markush.toast.error', '操作失败')), 'error')
        },
      },
    )
  }

  function handleUpdate(payload: {
    smiles?: string | null
    esmiles?: string | null
    normalized_label?: string | null
    raw_label?: string | null
    predicted_role?: 'complete' | 'scaffold' | 'fragment' | 'review_required' | null
    note?: string
  }) {
    const candidate = detail.data
    if (!candidate) return
    update.mutate(
      {
        library_root: libraryRoot,
        entity_id: candidate.candidate_id,
        expected_version: candidate.review_version,
        ...payload,
      },
      {
        onSuccess: () => showToast(t('markush.toast.updated', '已保存修改'), 'success'),
        onError: (err: unknown) =>
          showToast(getUserFacingError(err, t('markush.toast.error', '操作失败')), 'error'),
      },
    )
  }

  return (
    <div
      style={{
        display: 'grid',
        gridTemplateColumns: '320px 1fr 360px',
        gap: 12,
        height: '100%',
        minHeight: 0,
        padding: 12,
        background: 'var(--bg-base)',
      }}
    >
      <MarkushQueue
        title={t('markush.queue.title', '审查队列')}
        loading={list.isLoading}
        error={list.error ? getUserFacingError(list.error) : null}
        items={list.data?.items ?? []}
        total={list.data?.total ?? 0}
        filterStatus={filterStatus}
        onFilterChange={setFilterStatus}
        selectedCandidateId={selectedCandidateId}
        onSelect={setSelectedCandidateId}
      />
      <MarkushEvidencePane
        candidate={detail.data ?? null}
        loading={detail.isLoading}
        error={detail.error ? getUserFacingError(detail.error) : null}
      />
      <MarkushReviewPanel
        candidate={detail.data ?? null}
        loading={detail.isLoading}
        saving={decision.isPending || update.isPending}
        libraryRoot={libraryRoot}
        onDecide={handleDecision}
        onUpdate={handleUpdate}
      />
    </div>
  )
}