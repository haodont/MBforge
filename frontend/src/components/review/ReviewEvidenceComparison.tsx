import { useEffect, useState } from 'react'
import type { ReviewQueueItem } from '@/api/http/review'
import { smilesToRdkitSvg } from '@/api/http/molecule'
import Button from '@/components/ui/Button'

interface ReviewEvidenceComparisonProps {
  item: ReviewQueueItem
  cropUrl: string | null
  libraryRoot: string | null
  onOpenPdf: (docId: string, page: number | null, bbox: ReviewQueueItem['bbox']) => void
}

const imageStyle: React.CSSProperties = {
  display: 'block',
  width: '100%',
  height: 260,
  objectFit: 'contain',
  border: '1px solid var(--border)',
  borderRadius: 6,
  background: '#fff',
}

const unavailableStyle: React.CSSProperties = {
  ...imageStyle,
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'center',
  boxSizing: 'border-box',
  padding: 12,
  color: 'var(--text-muted)',
  fontSize: 13,
  textAlign: 'center',
}

export default function ReviewEvidenceComparison({
  item,
  cropUrl,
  libraryRoot,
  onOpenPdf,
}: ReviewEvidenceComparisonProps) {
  const [rdkitSvg, setRdkitSvg] = useState<string | null>(null)
  const [renderError, setRenderError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setRdkitSvg(null)
    setRenderError(null)
    if (!item.smiles) return () => { cancelled = true }

    smilesToRdkitSvg(item.smiles)
      .then((svg) => {
        if (!cancelled) setRdkitSvg(svg)
      })
      .catch((error: unknown) => {
        if (!cancelled) {
          setRenderError(error instanceof Error ? error.message : '未知错误')
        }
      })
    return () => { cancelled = true }
  }, [item.smiles])

  const sourceLabel = item.doc_id
    ? `来源：${item.doc_id}${item.page != null ? ` · 第 ${item.page} 页` : ''}`
    : '来源：无来源文档'
  const canOpenSource = Boolean(libraryRoot && item.doc_id)

  return (
    <section
      aria-label="参比证据"
      style={{
        display: 'flex',
        flexDirection: 'column',
        gap: 12,
        padding: 14,
        border: '1px solid var(--border)',
        borderRadius: 8,
        background: 'var(--bg-surface)',
      }}
    >
      <div>
        <div style={{ marginBottom: 6, fontSize: 13, fontWeight: 600 }}>来源结构</div>
        {cropUrl ? (
          <img src={cropUrl} alt="来源结构图" style={imageStyle} loading="lazy" />
        ) : (
          <div style={unavailableStyle}>暂无来源结构图</div>
        )}
      </div>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12 }}>
        <span style={{ color: 'var(--text-secondary)', fontSize: 13 }}>{sourceLabel}</span>
        <Button size="sm" variant="ghost" disabled={!canOpenSource} onClick={() => { if (item.doc_id) onOpenPdf(item.doc_id, item.page, item.bbox) }}>
          打开原文
        </Button>
      </div>
      <div>
        <div style={{ marginBottom: 6, fontSize: 13, fontWeight: 600 }}>RDKit 2D</div>
        {!item.smiles ? (
          <div style={unavailableStyle}>暂无 SMILES，无法生成 RDKit 2D 结构图</div>
        ) : renderError ? (
          <div style={unavailableStyle}>RDKit 2D 结构图生成失败：{renderError}</div>
        ) : rdkitSvg ? (
          <img
            src={`data:image/svg+xml;charset=utf-8,${encodeURIComponent(rdkitSvg)}`}
            alt="RDKit 2D 结构图"
            style={imageStyle}
          />
        ) : (
          <div style={unavailableStyle}>正在生成 RDKit 2D 结构图</div>
        )}
      </div>
      <div>
        <div style={{ marginBottom: 4, fontSize: 13, fontWeight: 600 }}>SMILES</div>
        <code style={{ display: 'block', overflowWrap: 'anywhere', color: 'var(--text-secondary)' }}>
          {item.smiles ?? '暂无 SMILES'}
        </code>
      </div>
    </section>
  )
}
