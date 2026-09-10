/** Center column: raw evidence + editable structure preview. */

import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { smilesToRdkitSvg } from '@/api/http/molecule'
import type { MarkushCandidateDetail } from '@/api/http/markush'
import EmptyState from '../ui/EmptyState'
import { ErrorState } from '../ui/ErrorState'
import { LoadingState } from '../ui/LoadingState'
import Tag from '../ui/Tag'

interface MarkushEvidencePaneProps {
  candidate: MarkushCandidateDetail | null
  loading: boolean
  error: string | null
}

export default function MarkushEvidencePane({
  candidate,
  loading,
  error,
}: MarkushEvidencePaneProps) {
  const { t } = useTranslation()
  const [rdkitSvg, setRdkitSvg] = useState<string | null>(null)
  const [renderError, setRenderError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setRdkitSvg(null)
    setRenderError(null)
    if (!candidate?.smiles) {
      return
    }
    smilesToRdkitSvg(candidate.smiles)
      .then((svg) => {
        if (!cancelled) setRdkitSvg(svg)
      })
      .catch((e: unknown) => {
        if (!cancelled) {
          setRenderError(e instanceof Error ? e.message : t('markush.evidence.rdkitFailed', 'RDKit 无法渲染'))
        }
      })
    return () => {
      cancelled = true
    }
  }, [candidate?.smiles, t])

  if (loading) {
    return (
      <section style={panelStyle}>
        <LoadingState variant="spinner" message={t('common.loading', '加载中…')} />
      </section>
    )
  }
  if (error) {
    return (
      <section style={panelStyle}>
        <ErrorState error={error} compact />
      </section>
    )
  }
  if (!candidate) {
    return (
      <section style={panelStyle}>
        <EmptyState message={t('markush.evidence.empty', '从左侧队列选择一条候选以查看证据。')} />
      </section>
    )
  }

  return (
    <section
      data-testid="markush-evidence-pane"
      style={{ ...panelStyle, overflowY: 'auto' }}
    >
      <header style={headerStyle}>
        <div style={{ fontSize: 14, fontWeight: 600 }}>
          {t('markush.evidence.title', '结构与原始证据')}
        </div>
        <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>
          {candidate.doc_id} · {candidate.normalized_label || candidate.raw_label || '—'}
        </div>
      </header>

      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))',
          gap: 14,
          padding: 14,
        }}
      >
        <Pane label={t('markush.evidence.currentStructure', '当前 E-SMILES 结构')}>
          {renderError ? (
            <div style={unavailableStyle}>{renderError}</div>
          ) : rdkitSvg ? (
            <img
              src={`data:image/svg+xml;charset=utf-8,${encodeURIComponent(rdkitSvg)}`}
              alt={t('markush.evidence.rdkitAlt', '当前结构图')}
              style={imageStyle}
            />
          ) : (
            <div style={unavailableStyle}>{t('markush.evidence.rendering', '正在生成结构图…')}</div>
          )}
          <code
            style={{
              display: 'block',
              marginTop: 8,
              fontFamily: "'Consolas', 'Monaco', monospace",
              fontSize: 12,
              color: 'var(--text-secondary)',
              wordBreak: 'break-all',
            }}
          >
            {candidate.smiles || candidate.esmiles || '（无 SMILES）'}
          </code>
        </Pane>

        {(candidate.evidence || []).map((ev) => (
          <Pane
            key={ev.evidence_id}
            label={`${t('markush.evidence.evidence', '证据')} · ${ev.page ?? '?'} 页`}
          >
            {ev.crop_relpath ? (
              <img
                src={ev.crop_relpath}
                alt={`${candidate.doc_id} 第 ${ev.page ?? '?'} 页原始分子图`}
                style={imageStyle}
                loading="lazy"
              />
            ) : (
              <div style={unavailableStyle}>{t('markush.evidence.noCrop', '无原始裁剪图')}</div>
            )}
          </Pane>
        ))}
      </div>

      {candidate.reasons.length > 0 ? (
        <div style={{ padding: '0 14px 14px', fontSize: 12 }}>
          <div style={{ fontWeight: 600, marginBottom: 6 }}>
            {t('markush.evidence.reasons', '分类原因')}
          </div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
            {candidate.reasons.map((reason) => (
              <Tag key={reason} tone="neutral">{reason}</Tag>
            ))}
          </div>
        </div>
      ) : null}

      {candidate.context_text ? (
        <div style={{ padding: '0 14px 14px', fontSize: 12 }}>
          <div style={{ fontWeight: 600, marginBottom: 6 }}>
            {t('markush.evidence.context', '上下文')}
          </div>
          <pre
            style={{
              margin: 0,
              padding: 10,
              background: 'var(--bg-base)',
              border: '1px solid var(--border)',
              borderRadius: 6,
              whiteSpace: 'pre-wrap',
              fontFamily: "'Consolas', 'Monaco', monospace",
              fontSize: 11,
              color: 'var(--text-secondary)',
            }}
          >
            {candidate.context_text}
          </pre>
        </div>
      ) : null}
    </section>
  )
}

const panelStyle: React.CSSProperties = {
  background: 'var(--bg-surface)',
  border: '1px solid var(--border)',
  borderRadius: 12,
  display: 'flex',
  flexDirection: 'column',
  minHeight: 0,
}

const headerStyle: React.CSSProperties = {
  padding: '12px 14px',
  borderBottom: '1px solid var(--border)',
  display: 'flex',
  flexDirection: 'column',
  gap: 4,
}

const imageStyle: React.CSSProperties = {
  display: 'block',
  width: '100%',
  height: 220,
  objectFit: 'contain',
  outline: '1px solid rgba(0, 0, 0, 0.1)',
  borderRadius: 6,
  background: '#fff',
}

const unavailableStyle: React.CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'center',
  height: 220,
  padding: 12,
  boxSizing: 'border-box',
  color: 'var(--text-muted)',
  fontSize: 12,
  textAlign: 'center',
  border: '1px dashed var(--border)',
  borderRadius: 6,
  background: 'var(--bg-base)',
}

function Pane({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div style={{ minWidth: 0 }}>
      <div
        style={{
          fontSize: 12,
          color: 'var(--text-muted)',
          fontWeight: 600,
          marginBottom: 8,
        }}
      >
        {label}
      </div>
      {children}
    </div>
  )
}