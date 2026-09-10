/** Right column: action buttons + editable fields + decision history. */

import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import type { MarkushCandidateDetail } from '@/api/http/markush'
import Button from '../ui/Button'
import Input from '../ui/Input'
import InlineAlert from '../ui/InlineAlert'
import SiteEditor from './SiteEditor'
import EnumerationPanel from './EnumerationPanel'

type DecisionAction = 'confirm_complete' | 'confirm_scaffold' | 'confirm_fragment' | 'reject' | 'reopen'

interface MarkushReviewPanelProps {
  candidate: MarkushCandidateDetail | null
  loading: boolean
  saving: boolean
  libraryRoot: string
  onDecide: (action: DecisionAction) => void
  onUpdate: (payload: {
    smiles?: string | null
    esmiles?: string | null
    normalized_label?: string | null
    raw_label?: string | null
    predicted_role?: 'complete' | 'scaffold' | 'fragment' | 'review_required' | null
    note?: string
  }) => void
}

export default function MarkushReviewPanel({
  candidate,
  loading,
  saving,
  libraryRoot,
  onDecide,
  onUpdate,
}: MarkushReviewPanelProps) {
  const { t } = useTranslation()
  const [smiles, setSmiles] = useState('')
  const [normalizedLabel, setNormalizedLabel] = useState('')

  if (loading || !candidate) {
    return (
      <aside style={panelStyle}>
        <div style={placeholderStyle}>
          {loading
            ? t('common.loading', '加载中…')
            : t('markush.review.empty', '选择候选以进行审查。')}
        </div>
      </aside>
    )
  }

  const pending = candidate.review_status === 'pending'
  const confirmed = candidate.review_status === 'confirmed'

  return (
    <aside style={panelStyle} data-testid="markush-review-panel">
      <header style={headerStyle}>
        <div style={{ fontSize: 14, fontWeight: 600 }}>
          {t('markush.review.title', '审查 / 修正面板')}
        </div>
        <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>
          {candidate.review_status} · v{candidate.review_version}
        </div>
      </header>

      <div style={{ padding: 14, display: 'flex', flexDirection: 'column', gap: 12 }}>
        <Button
          variant="primary"
          disabled={!pending || saving}
          onClick={() => onDecide('confirm_complete')}
        >
          {t('markush.review.confirmComplete', '确认为具体分子')}
        </Button>
        <Button
          variant="secondary"
          disabled={!pending || saving}
          onClick={() => onDecide('confirm_scaffold')}
        >
          {t('markush.review.confirmScaffold', '确认为骨架')}
        </Button>
        <Button
          variant="secondary"
          disabled={!pending || saving}
          onClick={() => onDecide('confirm_fragment')}
        >
          {t('markush.review.confirmFragment', '确认为片段')}
        </Button>
        <Button
          variant="danger"
          disabled={!pending || saving}
          onClick={() => onDecide('reject')}
        >
          {t('markush.review.reject', '驳回')}
        </Button>
        <Button
          variant="ghost"
          disabled={!confirmed || saving}
          onClick={() => onDecide('reopen')}
        >
          {t('markush.review.reopen', '重新打开')}
        </Button>
      </div>

      <section style={{ padding: '0 14px 14px' }}>
        <div style={{ fontSize: 12, fontWeight: 600, marginBottom: 8 }}>
          {t('markush.review.edit', '修正候选')}
        </div>
        <Field
          label={t('markush.review.smiles', 'SMILES')}
          value={smiles || candidate.smiles || ''}
          onChange={setSmiles}
        />
        <Field
          label={t('markush.review.normalizedLabel', '规范化标签')}
          value={normalizedLabel || candidate.normalized_label || ''}
          onChange={setNormalizedLabel}
        />
        <Button
          variant="ghost"
          disabled={saving || !pending}
          onClick={() =>
            onUpdate({
              smiles: smiles || null,
              normalized_label: normalizedLabel || null,
            })
          }
        >
          {t('markush.review.save', '保存修改')}
        </Button>
      </section>

      <section
        style={{
          padding: '0 14px 14px',
          borderTop: '1px solid var(--border)',
          paddingTop: 12,
          marginTop: 4,
        }}
      >
        <div style={{ fontSize: 12, fontWeight: 600, marginBottom: 8 }}>
          {t('markush.review.history', '决策历史')}
        </div>
        <DecisionHistory decisions={candidate.decisions || []} />
      </section>

      {/* Phase 4: once a candidate has been confirmed as a scaffold, the
          backend exposes a stable ``scaffold_id``; the site editor can then
          attach explicit R-group positions. Candidates without one show a
          disabled hint state. */}
      <ScaffoldLinkPanel candidate={candidate} libraryRoot={libraryRoot} />

      <EnumerationBlockedHint candidate={candidate} />

      {/* Phase 6: enumeration panel appears only when the confirmed scaffold
          has a confirmed attachment site and fragment relationship. */}
      {candidate.enumeration_eligible && candidate.scaffold_id ? (
        <EnumerationPanel libraryRoot={libraryRoot} scaffoldId={candidate.scaffold_id} />
      ) : null}
    </aside>
  )
}

function DecisionHistory({ decisions }: { decisions: MarkushCandidateDetail['decisions'] }) {
  const { t } = useTranslation()
  if (!decisions || decisions.length === 0) {
    return (
      <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>
        {t('markush.review.noHistory', '暂无决策记录。')}
      </div>
    )
  }
  return (
    <ol style={{ listStyle: 'none', padding: 0, margin: 0, display: 'flex', flexDirection: 'column', gap: 6 }}>
      {decisions.map((d) => (
        <li
          key={d.decision_id}
          style={{
            padding: '6px 8px',
            background: 'var(--bg-base)',
            border: '1px solid var(--border)',
            borderRadius: 6,
            fontSize: 11,
            color: 'var(--text-secondary)',
          }}
        >
          <div style={{ fontWeight: 600 }}>{d.action}</div>
          <div style={{ marginTop: 2 }}>
            {d.previous_state ?? '∅'} → {d.new_state ?? '∅'}
          </div>
          {d.reason && (
            <div style={{ marginTop: 2, color: 'var(--text-muted)' }}>{d.reason}</div>
          )}
          {d.created_at && (
            <div style={{ marginTop: 2, color: 'var(--text-muted)', fontSize: 10 }}>{d.created_at}</div>
          )}
        </li>
      ))}
    </ol>
  )
}

/**
 * Show the Phase-4 SiteEditor when the candidate has been confirmed as
 * a scaffold and the backend exposes a stable ``scaffold_id``. Pending
 * candidates without a scaffold id show a disabled hint state.
 */
function ScaffoldLinkPanel({
  candidate,
  libraryRoot,
}: {
  candidate: MarkushCandidateDetail
  libraryRoot: string
}) {
  const { t } = useTranslation()
  const scaffoldId = candidate.scaffold_id ?? ''
  if (!scaffoldId) {
    return (
      <InlineAlert tone="info" style={{ margin: '0 14px 14px' }}>
        {t(
          'markush.site.awaitScaffoldId',
          '确认该候选为骨架后，下方将出现 attachment site 编辑器。',
        )}
      </InlineAlert>
    )
  }
  return <SiteEditor libraryRoot={libraryRoot} scaffoldId={scaffoldId} />
}

/** Show why a scaffold cannot be enumerated, if the backend provided reasons. */
function EnumerationBlockedHint({ candidate }: { candidate: MarkushCandidateDetail }) {
  const { t } = useTranslation()
  if (candidate.enumeration_eligible) return null
  const reasons = candidate.enumeration_block_reasons
  if (reasons.length === 0) return null
  return (
    <div data-testid="markush-enumeration-blocked" style={{ margin: '0 14px 14px' }}>
      <InlineAlert tone="warning" title={t('markush.enumeration.blocked', '枚举暂不可用')}>
        {reasons.map((reason) => (
          <div key={reason}>· {reason}</div>
        ))}
      </InlineAlert>
    </div>
  )
}

function Field({ label, value, onChange }: { label: string; value: string; onChange: (next: string) => void }) {
  return (
    <label style={{ display: 'flex', flexDirection: 'column', gap: 4, marginBottom: 8 }}>
      <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>{label}</span>
      <Input
        type="text"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        style={{
          fontFamily: "'Consolas', 'Monospace', monospace",
          fontSize: 12,
        }}
      />
    </label>
  )
}

const panelStyle: React.CSSProperties = {
  background: 'var(--bg-surface)',
  border: '1px solid var(--border)',
  borderRadius: 12,
  display: 'flex',
  flexDirection: 'column',
  minHeight: 0,
  overflowY: 'auto',
}

const headerStyle: React.CSSProperties = {
  padding: '12px 14px',
  borderBottom: '1px solid var(--border)',
}

const placeholderStyle: React.CSSProperties = {
  flex: 1,
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'center',
  color: 'var(--text-muted)',
  fontSize: 13,
}