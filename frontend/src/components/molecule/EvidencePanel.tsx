import { useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import Button from '@/components/ui/Button'
import type { EvidenceItem } from '@/types'
import { smilesToRdkitSvg } from '@/api/http/molecule'
import type { MoleculeCorrection } from '@/api/http/molecule'
import SmilesDiff from './SmilesDiff'

interface EvidencePanelProps {
  items: EvidenceItem[]
  /** The current editable structure, used to compare against the source crop. */
  esmiles?: string
  libraryRoot: string | null
  molId?: string
  evidenceTotal?: number
  /** Called when the user clicks "打开原文" on a row. */
  onOpenPdf: (docId: string, page: number | null, bbox: EvidenceItem['bbox']) => void
}

/**
 * Vertical list of evidence rows for a single molecule.
 *
 * Each row shows: a 48x48 thumbnail (figure kind only), the document id,
 * the page number, and a "打开原文" button. The full-chain view is used in
 * the MoleculeDetailDrawer; the list view in the library table truncates
 * to 50 items.
 */
export default function EvidencePanel({
  items,
  esmiles,
  libraryRoot,
  molId,
  evidenceTotal,
  onOpenPdf,
}: EvidencePanelProps) {
  const { t } = useTranslation()
  const [expanded, setExpanded] = useState(false)
  const [corrections, setCorrections] = useState<MoleculeCorrection[]>([])
  const groups = useMemo(() => {
    const grouped = new Map<string, EvidenceItem[]>()
    for (const item of items) {
      const current = grouped.get(item.doc_id) ?? []
      current.push(item)
      grouped.set(item.doc_id, current)
    }
    return Array.from(grouped, ([docId, groupItems]) => ({ docId, items: groupItems }))
  }, [items])

  useEffect(() => {
    if (!libraryRoot || !molId) {
      setCorrections([])
      return
    }
    let cancelled = false
    void import('@/api/http/molecule')
      .then((module) => {
        if (typeof module.moleculeCorrections !== 'function') return []
        return module.moleculeCorrections(libraryRoot, molId)
      })
      .then((result) => {
        if (!cancelled) setCorrections(result)
      })
      .catch(() => {
        if (!cancelled) setCorrections([])
      })
    return () => { cancelled = true }
  }, [libraryRoot, molId])

  if (items.length === 0) {
    return null
  }
  const figureEvidence = items.find((item) => item.kind === 'figure' && item.crop_url)
  const visibleGroups = expanded ? groups : groups.slice(0, 3)
  const totalDocuments = evidenceTotal !== undefined
    ? new Set(items.map(item => item.doc_id)).size
    : groups.length
  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        gap: 6,
        padding: '10px 12px',
        background: 'var(--bg-base)',
        border: '1px solid var(--border)',
        borderRadius: 8,
      }}
    >
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          marginBottom: 4,
        }}
      >
        <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-secondary)' }}>
          <span>{t('evidence.chainTitle', { count: items.length })}</span>
          <span style={{ marginLeft: 8, color: 'var(--text-muted)' }}>
            {t('evidence.documentsCount', { count: totalDocuments })}
          </span>
        </div>
      </div>
      {esmiles && figureEvidence && (
        <StructureComparison
          evidence={figureEvidence}
          esmiles={esmiles}
        />
      )}
      {visibleGroups.map((group) => (
        <section key={group.docId} aria-label={group.docId}>
          <div style={{ padding: '4px 2px', color: 'var(--text-secondary)', fontSize: 12, fontWeight: 600 }}>
            {group.docId}
          </div>
          {group.items.map((ev) => (
            <EvidenceRow
              key={ev.id}
              ev={ev}
              libraryRoot={libraryRoot}
              onOpenPdf={onOpenPdf}
            />
          ))}
        </section>
      ))}
      {groups.length > 3 && (
        <Button
          size="sm"
          variant="ghost"
          onClick={() => setExpanded(value => !value)}
          style={{ alignSelf: 'flex-start', padding: '4px 0' }}
        >
          {expanded ? t('evidence.showLess') : t('evidence.showMore', { count: groups.length - 3 })}
        </Button>
      )}
      {corrections.length > 0 && <CorrectionHistory corrections={corrections} />}
    </div>
  )
}

function CorrectionHistory({ corrections }: { corrections: MoleculeCorrection[] }) {
  const { t } = useTranslation()
  return (
    <section aria-label={t('evidence.correctionHistory')} style={{ marginTop: 8 }}>
      <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-secondary)', marginBottom: 6 }}>
        {t('evidence.correctionHistory')}
      </div>
      {corrections.map((correction) => (
        <div key={correction.correction_id} style={{ padding: '6px 0', borderTop: '1px solid var(--border)' }}>
          <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>
            {correction.created_at} · {correction.source}
          </div>
          {(correction.field === 'esmiles' || correction.field === 'smiles') && correction.old_value && correction.new_value ? (
            <SmilesDiff before={correction.old_value} after={correction.new_value} />
          ) : (
            <div style={{ fontSize: 12 }}>{correction.field}</div>
          )}
        </div>
      ))}
    </section>
  )
}

function StructureComparison({ evidence, esmiles }: { evidence: EvidenceItem; esmiles: string }) {
  const { t } = useTranslation()
  const [rdkitSvg, setRdkitSvg] = useState<string | null>(null)
  const [renderError, setRenderError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setRdkitSvg(null)
    setRenderError(null)
    smilesToRdkitSvg(esmiles)
      .then((svg) => {
        if (!cancelled) setRdkitSvg(svg)
      })
      .catch((error: unknown) => {
        if (!cancelled) {
          setRenderError(error instanceof Error ? error.message : t('evidence.rdkitRenderError'))
        }
      })
    return () => { cancelled = true }
  }, [esmiles, t])

  if (!evidence.crop_url) return null

  return (
    <section
      aria-label={t('evidence.structureComparison')}
      style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))',
        gap: 14,
        padding: 14,
        border: '1px solid var(--border)',
        borderRadius: 8,
        background: 'var(--bg-surface)',
      }}
    >
      <StructurePane label={t('evidence.originalEvidence')}>
        <img
          src={evidence.crop_url}
          alt={t('evidence.originalEvidenceAlt', { docId: evidence.doc_id })}
          style={structureImageStyle}
          loading="lazy"
        />
      </StructurePane>
      <StructurePane label={t('evidence.currentEsiles')}>
        {renderError ? (
          <div style={structureUnavailableStyle}>{renderError}</div>
        ) : rdkitSvg ? (
          <img
            src={`data:image/svg+xml;charset=utf-8,${encodeURIComponent(rdkitSvg)}`}
            alt={t('evidence.currentRdkitAlt')}
            style={structureImageStyle}
          />
        ) : (
          <div style={structureUnavailableStyle}>{t('evidence.generatingRdkit')}</div>
        )}
      </StructurePane>
    </section>
  )
}

function StructurePane({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div style={{ minWidth: 0 }}>
      <div style={{ marginBottom: 8, color: 'var(--text-muted)', fontSize: 12, fontWeight: 600 }}>
        {label}
      </div>
      {children}
    </div>
  )
}

const structureImageStyle: React.CSSProperties = {
  display: 'block',
  width: '100%',
  height: 220,
  objectFit: 'contain',
  outline: '1px solid rgba(0, 0, 0, 0.1)',
  borderRadius: 6,
  background: '#fff',
}

const structureUnavailableStyle: React.CSSProperties = {
  ...structureImageStyle,
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'center',
  padding: 12,
  boxSizing: 'border-box',
  color: 'var(--text-muted)',
  fontSize: 12,
  lineHeight: 1.5,
  textAlign: 'center',
}

interface RowProps {
  ev: EvidenceItem
  libraryRoot: string | null
  onOpenPdf: EvidencePanelProps['onOpenPdf']
}

function EvidenceRow({ ev, libraryRoot, onOpenPdf }: RowProps) {
  const { t } = useTranslation()
  const kindLabel = ev.kind === 'figure' ? t('evidence.kindFigure') : ev.kind === 'text' ? t('evidence.kindText') : t('evidence.kindTable')
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 12,
        padding: '8px 10px',
        background: 'var(--bg-surface)',
        border: '1px solid var(--border)',
        borderRadius: 6,
        fontSize: 12,
      }}
    >
      {ev.kind === 'figure' && ev.crop_url ? (
        <img
          src={ev.crop_url}
          alt={`${ev.doc_id} crop`}
          style={{
            width: 48,
            height: 48,
            objectFit: 'contain',
            background: '#fff',
            border: '1px solid var(--border)',
            borderRadius: 4,
            flexShrink: 0,
          }}
          loading="lazy"
        />
      ) : (
        <div
          style={{
            width: 48,
            height: 48,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            background: 'var(--bg-base)',
            border: '1px solid var(--border)',
            borderRadius: 4,
            fontSize: 18,
            color: 'var(--text-muted)',
            flexShrink: 0,
          }}
        >
          {kindLabel}
        </div>
      )}
      <div style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column', gap: 2 }}>
        <div
          style={{
            fontSize: 13,
            fontWeight: 500,
            color: 'var(--text-primary)',
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            whiteSpace: 'nowrap',
          }}
          title={ev.doc_id}
        >
          {ev.doc_id}
        </div>
        <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>
          {ev.kind === 'figure' && ev.page != null ? t('evidence.pageNumber', { page: ev.page }) : null}
          {ev.kind === 'text' ? t('evidence.textMention') : null}
          {ev.kind === 'table' ? t('evidence.tableEvidence') : null}
          {ev.confidence != null ? t('evidence.confidence', { pct: (ev.confidence * 100).toFixed(0) }) : null}
        </div>
      </div>
      <Button
        size="sm"
        variant="primary"
        onClick={() => onOpenPdf(ev.doc_id, ev.page, ev.bbox)}
        disabled={!libraryRoot}
        title={!libraryRoot ? t('evidence.noLibraryRoot') : t('evidence.openInPdf')}
        style={{ minHeight: 32, flexShrink: 0 }}
      >
        {t('evidence.openOriginal')}
      </Button>
    </div>
  )
}
