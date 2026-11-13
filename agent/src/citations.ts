/**
 * Program-built source citations for the agent CLI.
 *
 * The model writes facts and cites them with an opaque `[[ev:<evidence_id>]]`
 * marker; it never writes URLs. This module resolves markers against evidence
 * returned by capability tools and renders them as markdown links to the
 * frontend deep-link route, which pi draws as clickable OSC 8 hyperlinks.
 */

export interface EvidenceLocation {
  id: string
  docId: string
  page: number
  bbox?: [number, number, number, number]
}

const evidenceById = new Map<string, EvidenceLocation>()

export function rememberEvidence(location: EvidenceLocation): void {
  evidenceById.set(location.id, location)
}

export function clearEvidence(): void {
  evidenceById.clear()
}

/**
 * Base URL of the workbench UI that agent links open.
 *
 * `MBFORGE_FRONTEND_URL` wins (single-port deployments serve the SPA from the
 * API). Otherwise follow the same host/port variables `dev:all` binds Vite to,
 * so an overridden dev stack still produces working links.
 */
export function frontendBaseUrl(): string {
  const configured = process.env.MBFORGE_FRONTEND_URL?.trim()
  if (configured) return configured.replace(/\/+$/, '')
  const host = process.env.MBFORGE_DEV_HOST?.trim() || 'localhost'
  const port = process.env.MBFORGE_DEV_FRONTEND_PORT?.trim() || '5173'
  return `http://${host}:${port}`
}

export function evidenceDeepLink(location: EvidenceLocation): string {
  const params = new URLSearchParams({
    doc: location.docId,
    page: String(location.page),
    evidence: location.id,
  })
  if (location.bbox) params.set('bbox', location.bbox.join(','))
  return `${frontendBaseUrl()}/open?${params.toString()}`
}

const CITATION_PATTERN = /\[\[ev:([^\]\s]+)\]\]/g

export function linkifyCitations(markdown: string): string {
  return markdown.replace(CITATION_PATTERN, (match, id: string) => {
    const location = evidenceById.get(id)
    // Unknown markers stay literal rather than fabricating a link.
    if (!location) return match
    return `[来源·p.${location.page}](${evidenceDeepLink(location)})`
  })
}

const CITATION_TOOLS = new Set([
  'search_evidence',
  'list_evidence',
  'verify_structures',
])

/** Tools whose rows belong to the document the call named, not to the row. */
const DOCUMENT_SCOPED_TOOLS = new Set(['list_evidence', 'verify_structures'])

export function citationGuidelines(toolName: string): string[] | undefined {
  if (!CITATION_TOOLS.has(toolName)) return undefined
  return [
    `When you state a fact from ${toolName} results, cite it inline as [[ev:<evidence_id>]] using the exact evidence_id returned. Write only the fact and this marker; never write URLs or markdown links, because the workbench converts the marker into a clickable source link automatically.`,
  ]
}

/** Extract citable evidence locations from a capability result. */
export function harvestEvidence(
  toolName: string,
  params: Record<string, unknown>,
  data: unknown,
): EvidenceLocation[] {
  if (!CITATION_TOOLS.has(toolName)) return []
  if (typeof data !== 'object' || data === null) return []
  const items = (data as { items?: unknown }).items
  if (!Array.isArray(items)) return []

  const locations: EvidenceLocation[] = []
  const resultDocId =
    'doc_id' in data && typeof data.doc_id === 'string'
      ? data.doc_id
      : undefined
  for (const item of items) {
    if (typeof item !== 'object' || item === null) continue
    const record = item as {
      evidence_id?: unknown
      doc_id?: unknown
      page?: unknown
      bbox?: unknown
    }
    const id =
      typeof record.evidence_id === 'string' ? record.evidence_id : undefined
    const page = typeof record.page === 'number' ? record.page : undefined
    if (!id || page === undefined) continue
    // Prefer the canonical document id echoed by the result. Document-scoped
    // tools can be called with a title or short id; params.doc_id is then not
    // safe to put in a deep link.
    const docId =
      resultDocId ??
      (DOCUMENT_SCOPED_TOOLS.has(toolName)
        ? typeof params.doc_id === 'string'
          ? params.doc_id
          : undefined
        : typeof record.doc_id === 'string'
          ? record.doc_id
          : undefined)
    if (!docId) continue
    const bbox =
      Array.isArray(record.bbox) &&
      record.bbox.length === 4 &&
      record.bbox.every((value) => typeof value === 'number')
        ? (record.bbox as [number, number, number, number])
        : undefined
    locations.push({ id, docId, page, bbox })
  }
  return locations
}
