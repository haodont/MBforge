/** Inline review card: the assistant proposed a correction, the human decides. */
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import Button from '@/components/ui/Button'
import Badge from '@/components/ui/Badge'
import { reviewDecide, reviewDecideFiltered } from '@/api/http/review'
import type { ResearchReviewReference } from '@/api/http/research'
import { showToast } from '@/hooks/useToast'
import { getUserFacingError } from '@/utils/errors'

interface ResearchReviewCardProps {
  reference: ResearchReviewReference
  libraryRoot: string
  busy?: boolean
  onDecided: (status: 'confirmed' | 'rejected') => void
  onBatchDecided?: (ids: string[], status: 'confirmed') => void
}

export default function ResearchReviewCard({ reference, libraryRoot, busy, onDecided, onBatchDecided }: ResearchReviewCardProps) {
  const { t } = useTranslation()
  const [pending, setPending] = useState(false)
  const [error, setError] = useState('')
  const [status, setStatus] = useState(reference.status ?? 'pending')
  const disabled = busy || pending || status !== 'pending'

  const decide = async (action: 'confirm' | 'reject') => {
    setPending(true)
    setError('')
    try {
      await reviewDecide(libraryRoot, [{ kind: 'ai_review', id: reference.item_id }], action)
      const next = action === 'confirm' ? 'confirmed' : 'rejected'
      setStatus(next)
      onDecided(next)
    } catch (err) {
      setError(getUserFacingError(err))
    } finally {
      setPending(false)
    }
  }

  // Batch paths: the whole document, or every text-level proposal.
  const decideBatch = async (filter: { docId?: string; targetKind?: string }) => {
    setPending(true)
    setError('')
    try {
      const result = await reviewDecideFiltered(libraryRoot, { kind: 'ai_review', ...filter }, 'confirm')
      const ids = result.results.filter(item => item.status === 'confirmed').map(item => item.id)
      onBatchDecided?.(ids, 'confirmed')
      showToast(t('review.aiProposal.batchDone', { count: result.updated }), 'success')
    } catch (err) {
      setError(getUserFacingError(err))
    } finally {
      setPending(false)
    }
  }

  return (
    <section className="research-review-card" aria-label={t('review.aiProposal.title')}>
      <div className="research-review-card__head">
        <Badge tone="neutral">{t('review.kind.ai_review')}</Badge>
        <span>{t('review.aiProposal.target', { kind: reference.target_kind || '—', id: reference.target_id || reference.item_id })}</span>
        {status !== 'pending' && <Badge tone={status === 'confirmed' ? 'success' : 'danger'}>{t('review.status.' + status)}</Badge>}
      </div>
      <p className="research-review-card__change">
        <strong>{reference.field || 'name'}</strong>: {reference.before_actual || '—'} → {reference.after || '—'}
      </p>
      {reference.rationale && <p className="research-review-card__reason">{reference.rationale}</p>}
      {error && <p className="research-review-card__error">{error}</p>}
      <div className="research-review-card__actions">
        <Button size="sm" disabled={disabled} onClick={() => void decide('confirm')}>{t('review.confirm')}</Button>
        <Button size="sm" variant="ghost" disabled={disabled} onClick={() => void decide('reject')}>{t('review.reject')}</Button>
        <Button size="sm" variant="ghost" disabled={pending} onClick={() => void decideBatch({ docId: reference.doc_id || undefined })}>{t('review.aiProposal.approveDoc')}</Button>
        <Button size="sm" variant="ghost" disabled={pending} onClick={() => void decideBatch({ targetKind: 'evidence' })}>{t('review.aiProposal.approveText')}</Button>
      </div>
    </section>
  )
}
