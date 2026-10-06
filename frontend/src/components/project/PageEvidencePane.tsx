import { useEffect, useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import { useDocumentEvidence } from '@/api/query/hooks'
import type { DocumentEvidenceItem } from '@/api/http/library'
import Badge from '@/components/ui/Badge'
import { Panel } from '@/components/ui/Panel'
import Spinner from '@/components/ui/Spinner'

interface PageEvidencePaneProps {
  docId: string
  page: number
  libraryRoot: string
  selectedEvidenceId?: string | null
}

/** One rendered line of a block, at the indent level the layout gave it. */
interface EvidenceLine {
  line: number
  level: number
  items: DocumentEvidenceItem[]
}

/** One rendered block: a whole patent paragraph, or a single non-prose row. */
interface EvidenceGroup {
  id: string
  paragraphNumber: string | null
  /** The paragraph started on an earlier page; this is its tail. */
  continued: boolean
  lines: EvidenceLine[]
  items: DocumentEvidenceItem[]
}

function panelTitle(title: string, count: number) {
  return (
    <div className="pdf-evidence-panel-title">
      <span>{title}</span>
      <Badge tone="neutral">{count}</Badge>
    </div>
  )
}

function lineContent(line: EvidenceLine, fallback: string): string {
  const text = line.items
    .map(item => item.raw_text.trim())
    .filter(Boolean)
    .join(' ')
  return text || fallback
}

/**
 * Gather text rows that share a paragraph into one block, and their rows into
 * the paragraph's own lines.
 *
 * The reader annotates every row with the paragraph and line it belongs to, so
 * a paragraph the layout split across regions, lines or pages renders once,
 * with the indentation the document actually had. Rows outside a paragraph keep
 * their own block.
 */
function groupEvidence(items: DocumentEvidenceItem[]): EvidenceGroup[] {
  const groups: EvidenceGroup[] = []
  const byParagraph = new Map<string, EvidenceGroup>()
  const lineOf = (group: EvidenceGroup, item: DocumentEvidenceItem): EvidenceLine => {
    const existing = group.lines.find(line => line.line === item.paragraph_line)
    if (existing) return existing
    const line: EvidenceLine = {
      line: item.paragraph_line,
      level: item.indent_level,
      items: [],
    }
    group.lines.push(line)
    return line
  }
  for (const item of items) {
    if (item.category === 'text' && item.paragraph_id) {
      let group = byParagraph.get(item.paragraph_id)
      if (!group) {
        group = {
          id: item.paragraph_id,
          paragraphNumber: item.paragraph_number,
          continued: !item.paragraph_start,
          lines: [],
          items: [],
        }
        byParagraph.set(item.paragraph_id, group)
        groups.push(group)
      }
      group.items.push(item)
      lineOf(group, item).items.push(item)
      continue
    }
    const group: EvidenceGroup = {
      id: item.evidence_id,
      paragraphNumber: null,
      continued: false,
      lines: [{ line: 0, level: 0, items: [item] }],
      items: [item],
    }
    groups.push(group)
  }
  return groups
}

export default function PageEvidencePane({ docId, page, libraryRoot, selectedEvidenceId }: PageEvidencePaneProps) {
  const { t } = useTranslation()
  const { data, isLoading } = useDocumentEvidence(docId, page, libraryRoot)
  const items = data?.ok ? data.data : null
  const error = data && !data.ok ? data.error : null

  const groups = useMemo(() => groupEvidence(items ?? []), [items])
  const anchorByEvidenceId = useMemo(() => {
    const anchors = new Map<string, string>()
    for (const group of groups) {
      for (const item of group.items) anchors.set(item.evidence_id, group.id)
    }
    return anchors
  }, [groups])

  useEffect(() => {
    if (!selectedEvidenceId) return
    const anchor = anchorByEvidenceId.get(selectedEvidenceId)
    if (!anchor) return
    document.getElementById(`pdf-evidence-${anchor}`)?.scrollIntoView({ block: 'nearest' })
  }, [anchorByEvidenceId, selectedEvidenceId])

  if (isLoading || (!items && !error)) {
    return (
      <div className="pdf-evidence-state">
        <Spinner />
        <span>{t('pdf.evidenceLoading')}</span>
      </div>
    )
  }
  if (error) {
    return <div className="pdf-evidence-state pdf-evidence-state--error">{error}</div>
  }
  if (!items) return null

  return (
    <div className="pdf-evidence-pane">
      <div className="pdf-evidence-source">
        <span>{t('pdf.evidenceSource')}</span>
        <Badge tone="info">{t('pdf.evidencePage', { page })}</Badge>
      </div>
      <Panel
        title={panelTitle(t('pdf.evidenceTitle'), groups.length)}
        className="pdf-evidence-panel"
      >
        {groups.length === 0 ? (
          <div className="pdf-evidence-empty">{t('pdf.evidenceEmpty')}</div>
        ) : (
          <div className="pdf-evidence-list">
            {groups.map((group) => {
              const header = group.items[0]
              const isSelected = group.items.some(
                item => item.evidence_id === selectedEvidenceId,
              )
              return (
                <article
                  id={`pdf-evidence-${group.id}`}
                  className={`pdf-evidence-item${isSelected ? ' is-selected' : ''}`}
                  aria-current={isSelected ? 'true' : undefined}
                  key={group.id}
                >
                  <div className="pdf-evidence-item__topline">
                    {group.paragraphNumber ? (
                      <Badge tone="info">{`[${group.paragraphNumber}]`}</Badge>
                    ) : (
                      <Badge tone={header.category === 'text' ? 'neutral' : 'info'}>
                        {header.kind}
                      </Badge>
                    )}
                    {group.continued && (
                      <span className="pdf-evidence-item__continued">
                        {t('pdf.evidenceContinued')}
                      </span>
                    )}
                    <code>{header.evidence_id}</code>
                  </div>
                  {group.lines.map(line => (
                    <p
                      key={line.line}
                      style={line.level > 0 ? { paddingLeft: `${line.level * 1.25}em` } : undefined}
                    >
                      {lineContent(line, t('pdf.evidenceNoRawText'))}
                    </p>
                  ))}
                </article>
              )
            })}
          </div>
        )}
      </Panel>
    </div>
  )
}
