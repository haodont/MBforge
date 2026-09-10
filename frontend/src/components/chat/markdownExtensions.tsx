import { Suspense, lazy, useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import DOMPurify from 'dompurify'
import { isSmiles, smilesToImgUrl } from './chatUtils'
import { smilesToRdkitSvg } from '@/api/http/molecule'
import { openExternalUrl } from '@/api/http/_utils'

const MermaidCode = lazy(() =>
  import('../ui/MermaidCode').then(m => ({ default: m.MermaidCode }))
)

function parseMoleCodeMetadata(code: string): { page: number | null; smiles: string | null } {
  let page: number | null = null
  let smiles: string | null = null
  for (const line of code.split('\n').slice(0, 4)) {
    const pageMatch = /%%\s*page\s*=\s*(\d+)/i.exec(line)
    if (pageMatch) page = parseInt(pageMatch[1], 10)
    const smilesMatch = /%%\s*smiles\s*=\s*(.+)$/i.exec(line)
    if (smilesMatch) smiles = smilesMatch[1].trim()
  }
  return { page, smiles }
}

export function RdkitStructure({ smiles }: { smiles: string }) {
  const [svg, setSvg] = useState('')
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setSvg('')
    setError(null)
    void smilesToRdkitSvg(smiles, 420, 260)
      .then(rawSvg => {
        if (!cancelled) setSvg(DOMPurify.sanitize(rawSvg, { USE_PROFILES: { svg: true } }))
      })
      .catch((reason: unknown) => {
        if (!cancelled) setError(reason instanceof Error ? reason.message : String(reason))
      })
    return () => { cancelled = true }
  }, [smiles])

  if (error) return <pre className="molecode-fallback"><code>{smiles}</code></pre>
  if (!svg) return <div className="molecode-loading">正在生成 RDKit 结构图…</div>
  return <div className="molecode-rdkit-svg" dangerouslySetInnerHTML={{ __html: svg }} />
}

export interface MoleculeClickInfo {
  /** 1-based page number (extracted from `%% page=N` mermaid comment). */
  page: number
}

interface CodeBlockProps {
  className?: string
  children?: ReactNode
  node?: unknown
  /** Called when the user clicks a Mermaid block. */
  onMoleculeClick?: (info: MoleculeClickInfo) => void
}

/** Parse `%% page=3` from the first line(s) of a mermaid block. */
function parseMermaidPage(code: string): number | null {
  for (const line of code.split('\n').slice(0, 3)) {
    const m = /%%\s*page\s*=\s*(\d+)/i.exec(line)
    if (m) return parseInt(m[1], 10)
  }
  return null
}

/**
 * Render a `<code>` block inside a Markdown document.
 *
 * - `language-mermaid` → Mermaid SVG (clickable if `onMoleculeClick` set)
 * - Bare SMILES in inline code → image render (chat-style)
 * - Other code blocks → plain wrapped `<code>`
 * - Inline code (no className) → `<code>` pass-through
 */
export function MermaidAwareCodeBlock({
  className,
  children,
  onMoleculeClick,
}: CodeBlockProps) {
  const raw = children ?? ''
  const text = (typeof raw === 'string' ? raw : typeof raw === 'number' ? String(raw) : '').trim()

  // Inline SMILES (chat only)
  if (!className && isSmiles(text)) {
    return (
      <span className="chat-smiles-inline">
        <img
          src={smilesToImgUrl(text)}
          alt={text}
          onClick={() => openExternalUrl(smilesToImgUrl(text))}
          onError={e => {
            ;(e.target as HTMLImageElement).style.display = 'none'
          }}
        />
        <code className="chat-smiles-code">{text}</code>
      </span>
    )
  }

  // Mermaid / MoleCode block
  if (className === 'language-mermaid' || className === 'language-molecode') {
    // Older pipeline outputs mislabeled MoleCode fences as mermaid. Inspect
    // the metadata instead of trusting the fence language so RDKit remains
    // the source of truth whenever a SMILES is available.
    const metadata = parseMoleCodeMetadata(text)
    const page = onMoleculeClick ? (metadata.page ?? parseMermaidPage(text)) : null
    return (
      <Suspense
        fallback={<div style={{ padding: 8, opacity: 0.6 }}>Loading diagram…</div>}
      >
        <div
          className="mermaid-block"
          data-page={page ?? undefined}
          onClick={
            page && onMoleculeClick
              ? () => onMoleculeClick({ page })
              : undefined
          }
          style={page && onMoleculeClick ? { cursor: 'pointer' } : undefined}
        >
          {metadata.smiles ? <RdkitStructure smiles={metadata.smiles} /> : <MermaidCode code={text} />}
        </div>
      </Suspense>
    )
  }

  // Other block-level code
  const isBlock = className?.startsWith('language-')
  if (isBlock) {
    return (
      <div className="chat-code-block">
        <code className={className}>{children}</code>
      </div>
    )
  }

  // Inline code
  return <code className="chat-inline-code">{children}</code>
}
