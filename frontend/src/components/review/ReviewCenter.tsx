import { useCallback, useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { CheckIcon, ExternalLinkIcon, RefreshCwIcon, TrashIcon, XIcon } from '@/components/icons'
import Button from '@/components/ui/Button'
import Chip from '@/components/ui/Chip'
import ConfirmDialog from '@/components/ui/ConfirmDialog'
import EmptyState from '@/components/ui/EmptyState'
import IconButton from '@/components/ui/IconButton'
import InlineAlert from '@/components/ui/InlineAlert'
import Pagination from '@/components/ui/Pagination'
import Select from '@/components/ui/Select'
import { cropImageUrl } from '@/api/http/library'
import { type ReviewAction, type ReviewKind, type ReviewQueueItem, type ReviewStatus } from '@/api/http/review'
import { useReviewClearAll, useReviewDecide, useReviewHistory, useReviewQueue, useReviewStats, toQueueItems } from '@/api/query/hooks/useReview'
import { useAppContext } from '@/context/AppContext'
import { useReviewHotkeys } from '@/hooks/useReviewHotkeys'
import { showToast } from '@/hooks/useToast'
import { getUserFacingError } from '@/utils/errors'
import ReviewEvidenceComparison from './ReviewEvidenceComparison'
import './ReviewCenter.css'

const KINDS: Array<'all' | ReviewKind> = ['all', 'low_conf_molecule', 'review_required', 'unparsable_smiles', 'activity_match', 'missing_evidence', 'ambiguous_coref', 'markush_link']
const PAGE_SIZE = 25

function labelForKind(kind: string, t: (key: string) => string): string {
  return t(`review.kind.${kind}`)
}

export default function ReviewCenter() {
  const { t } = useTranslation()
  const { libraryRoot, openTab } = useAppContext()
  const [kind, setKind] = useState<'all' | ReviewKind>('all')
  const [status, setStatus] = useState<ReviewStatus | ''>('pending')
  const [page, setPage] = useState(1)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [clearConfirmOpen, setClearConfirmOpen] = useState(false)

  const filters = useMemo<{ kind?: ReviewKind; status?: ReviewStatus; page: number; pageSize: number }>(() => ({
    kind: kind === 'all' ? undefined : kind,
    status: status || undefined,
    page,
    pageSize: PAGE_SIZE,
  }), [kind, page, status])

  const queueQuery = useReviewQueue(libraryRoot, filters)
  const statsQuery = useReviewStats(libraryRoot)
  const decideMutation = useReviewDecide()
  const clearAllMutation = useReviewClearAll()

  const items = toQueueItems(queueQuery.data?.items)
  const total = queueQuery.data?.total ?? 0
  const pending = statsQuery.data?.pending ?? 0
  const loading = queueQuery.isFetching || decideMutation.isPending || clearAllMutation.isPending
  const error = queueQuery.error ? getUserFacingError(queueQuery.error) : null

  const clearAll = useCallback(async () => {
    if (!libraryRoot) return
    setClearConfirmOpen(false)
    try {
      const result = await clearAllMutation.mutateAsync(libraryRoot)
      showToast(t('review.clearAllDone', { count: result.deleted_items + result.deleted_candidates }), 'success')
      setPage(1)
      setSelected(new Set())
      setSelectedId(null)
    } catch (err) {
      showToast(`${t('review.clearAllFailed')}: ${getUserFacingError(err)}`, 'error')
    }
  }, [libraryRoot, clearAllMutation, t])

  // Keep the selection valid as the queue changes (filter/page switch).
  useEffect(() => {
    setSelectedId(current => items.some(item => item.id === current) ? current : items[0]?.id ?? null)
    setSelected(new Set())
  }, [items])

  const selectedItem = items.find(item => item.id === selectedId) ?? null
  const selectedItems = useMemo(
    () => items.filter(item => selected.has(item.id)).map(item => ({ kind: item.kind, id: item.id })),
    [items, selected],
  )
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE))
  const decide = useCallback(async (action: ReviewAction, decisionItems = selectedItems) => {
    if (!libraryRoot || decisionItems.length === 0) return
    await decideMutation.mutateAsync({ libraryRoot, items: decisionItems, action })
  }, [libraryRoot, decideMutation, selectedItems])
  const move = useCallback((offset: number) => {
    if (items.length === 0) return
    const index = items.findIndex(item => item.id === selectedId)
    const next = items[Math.max(0, Math.min(items.length - 1, index + offset))]
    setSelectedId(next.id)
  }, [items, selectedId])
  useReviewHotkeys(Boolean(selectedItem), {
    onNext: () => move(1),
    onPrevious: () => move(-1),
    onConfirm: () => { if (selectedItem) void decide('confirm', [{ kind: selectedItem.kind, id: selectedItem.id }]) },
    onReject: () => { if (selectedItem) void decide('reject', [{ kind: selectedItem.kind, id: selectedItem.id }]) },
  })

  const openSource = (item: ReviewQueueItem) => {
    if (!item.doc_id || !item.page) return
    const bbox = item.bbox
    openTab({
      type: 'document',
      title: item.doc_id,
      libraryRoot,
      doc: { doc_id: item.doc_id, title: item.doc_id, path: `storage/${item.doc_id}/source.pdf`, doc_type: 'pdf', added_at: '', hash: '' },
      initialPage: item.page,
      initialBbox: bbox && bbox.every(value => value !== null) ? bbox as [number, number, number, number] : undefined,
    })
  }

  if (!libraryRoot) return <div className="review-center"><p className="review-center__empty">{t('review.noLibrary')}</p></div>
  return (
    <main className="review-center" aria-label={t('review.title')}>
      <div className="review-center__header">
        <div><h1>{t('review.title')}</h1><span className="review-center__pending">{t('review.pending', { count: pending })}</span></div>
        <div className="review-center__header-actions">
          <Button variant="danger" icon={<TrashIcon size={15} />} onClick={() => setClearConfirmOpen(true)} disabled={clearAllMutation.isPending || pending === 0}>{t('review.clearAll')}</Button>
          <IconButton size={32} ariaLabel={t('review.refresh')} title={t('review.refresh')} onClick={() => void queueQuery.refetch()} disabled={loading}><RefreshCwIcon size={15} /></IconButton>
        </div>
      </div>
      <div className="review-center__toolbar">
        <div className="review-center__chips" aria-label={t('review.kindFilter')}>
          {KINDS.map(value => <Chip key={value} label={labelForKind(value, t)} active={kind === value} onClick={() => { setKind(value); setPage(1) }} />)}
        </div>
        <label className="review-center__status-filter">{t('review.status')}
          <Select value={status} onChange={value => { setStatus(value as ReviewStatus | ''); setPage(1) }}
            options={[
              { value: 'pending', label: t('review.status.pending') },
              { value: 'confirmed', label: t('review.status.confirmed') },
              { value: 'rejected', label: t('review.status.rejected') },
              { value: '', label: t('review.status.all') },
            ]} />
        </label>
      </div>
      {selected.size > 0 && (
        <div className="review-center__bulk"><span>{t('review.selected', { count: selected.size })}</span>
          <div className="review-center__bulk-actions">
            <Button size="sm" icon={<CheckIcon size={14} />} onClick={() => void decide('confirm')}>{t('review.confirm')}</Button>
            <Button size="sm" icon={<XIcon size={14} />} onClick={() => void decide('reject')}>{t('review.reject')}</Button>
          </div>
        </div>
      )}
      {error && <InlineAlert tone="danger">{error}</InlineAlert>}
      <div className="review-center__layout">
        <section className="review-center__list" aria-label={t('review.queue')}>
          {items.length === 0 && !loading && <EmptyState message={t('review.empty')} />}
          {items.map(item => (
            <button type="button" key={`${item.kind}:${item.id}`} className={`review-center__row${item.id === selectedId ? ' is-selected' : ''}`} onClick={() => setSelectedId(item.id)}>
              <input type="checkbox" aria-label={t('review.selectItem', { name: item.name ?? item.id })} checked={selected.has(item.id)} onChange={event => { event.stopPropagation(); setSelected(current => { const next = new Set(current); if (event.target.checked) next.add(item.id); else next.delete(item.id); return next }) }} onClick={event => event.stopPropagation()} />
              <span className="review-center__row-main"><span className="review-center__row-title">{item.name || item.smiles || item.id}</span><span className="review-center__row-meta">{labelForKind(item.kind, t)}{item.doc_id ? ` · ${item.doc_id}` : ''}{item.page ? ` · p.${item.page}` : ''}</span></span>
              <span className="review-center__status">{t(`review.status.${item.status}`)}</span>
            </button>
          ))}
          <div className="review-center__pagination">
            <Pagination current={page} total={totalPages} pageSize={PAGE_SIZE} totalItems={total} onChange={setPage} />
          </div>
        </section>
        <ReviewDetail item={selectedItem} t={t} onDecide={(action, choice) => { if (selectedItem) void decide(action, [{ kind: selectedItem.kind, id: selectedItem.id, ...(choice ? { choice } : {}) }]) }} onOpenSource={openSource} libraryRoot={libraryRoot} />
      </div>
      <ConfirmDialog open={clearConfirmOpen} title={t('review.clearAll')} message={t('review.clearAllConfirm')} confirmLabel={t('review.clearAll')} danger loading={clearAllMutation.isPending} onConfirm={() => void clearAll()} onCancel={() => setClearConfirmOpen(false)} />
    </main>
  )
}

function ReviewDetail({ item, t, onDecide, onOpenSource, libraryRoot }: { item: ReviewQueueItem | null; t: (key: string, options?: Record<string, unknown>) => string; onDecide: (action: ReviewAction, choice?: string | null) => void; onOpenSource: (item: ReviewQueueItem) => void; libraryRoot: string }) {
  const [choice, setChoice] = useState<string | null>(null)
  const itemId = item?.id ?? null
  const { data: history = [] } = useReviewHistory(libraryRoot, item ? item.id : null)
  useEffect(() => { setChoice(null) }, [itemId])
  if (!item) return <section className="review-center__detail"><p className="review-center__empty">{t('review.selectPrompt')}</p></section>
  const display = (value: unknown): string => typeof value === 'string' || typeof value === 'number' ? String(value) : ''
  const cropUrl = item.doc_id && item.crop_relpath ? cropImageUrl(item.doc_id, item.crop_relpath, libraryRoot) : null
  const coref = item.kind === 'ambiguous_coref' ? (item.payload as { ocr_labels?: string[]; coref_primary?: string }) : null
  return <section className="review-center__detail" aria-label={t('review.detail')}>
    <h2>{item.name || item.smiles || item.id}</h2>
    <div className="review-center__detail-meta">{labelForKind(item.kind, t)} · {t(`review.status.${item.status}`)}{item.confidence !== null ? ` · ${Math.round(item.confidence * 100)}%` : ''}</div>
    <div className="review-center__detail-actions">
      <Button size="sm" icon={<CheckIcon size={14} />} disabled={item.status !== 'pending'} onClick={() => onDecide('confirm')}>{t('review.confirm')}</Button>
      <Button size="sm" icon={<XIcon size={14} />} disabled={item.status !== 'pending'} onClick={() => onDecide('reject')}>{t('review.reject')}</Button>
      <Button size="sm" variant="ghost" disabled={item.status === 'pending'} onClick={() => onDecide('reopen')}>{t('review.reopen')}</Button>
      {item.doc_id && item.page && <Button size="sm" variant="ghost" icon={<ExternalLinkIcon size={14} />} onClick={() => onOpenSource(item)}>{t('review.openSource')}</Button>}
    </div>
    <ReviewEvidenceComparison item={item} cropUrl={cropUrl} libraryRoot={libraryRoot} onOpenPdf={(docId, page, bbox) => onOpenSource({ ...item, doc_id: docId, page, bbox })} />
    {coref && Array.isArray(coref.ocr_labels) && coref.ocr_labels.length > 0 && <div><strong>{t('review.corefLabels')}</strong><div role="radiogroup" aria-label={t('review.corefLabels')}>{coref.ocr_labels.map(label => <label key={label} style={{ display: 'block' }}><input type="radio" name={`coref-${item.id}`} checked={choice === label} onChange={() => setChoice(label)} /> {label}{label === coref.coref_primary ? ` · ${t('review.corefSuggested')}` : ''}</label>)}</div></div>}
    {item.smiles && <p><strong>SMILES</strong><br />{item.smiles}</p>}
    {item.reasons.length > 0 && <p><strong>{t('review.reasons')}</strong><br />{item.reasons.join(' · ')}</p>}
    {item.context_text && <div><strong>{t('review.context')}</strong><pre>{item.context_text}</pre></div>}
    <div><strong>{t('review.history')}</strong>{history.length === 0 ? <p className="review-center__detail-meta">{t('review.noHistory')}</p> : <ul>{history.map((entry, index) => <li key={index}>{display(entry.action)} · {display(entry.created_at)}{entry.reason ? ` · ${display(entry.reason)}` : ''}</li>)}</ul>}</div>
  </section>
}
