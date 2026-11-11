export interface EvidenceDeepLink {
  docId: string
  page?: number
  bbox?: [number, number, number, number]
  evidenceId?: string
}

/**
 * Parse the agent citation deep-link query (`/open?doc=&page=&bbox=&evidence=`).
 * Malformed page/bbox values are dropped rather than navigating to a wrong spot.
 */
export function parseEvidenceDeepLink(search: string): EvidenceDeepLink | null {
  const params = new URLSearchParams(search)
  const docId = params.get('doc')
  if (!docId) return null

  const pageRaw = Number(params.get('page'))
  const page = Number.isInteger(pageRaw) && pageRaw > 0 ? pageRaw : undefined

  const bboxRaw = params.get('bbox')?.split(',').map(Number)
  const bbox =
    bboxRaw && bboxRaw.length === 4 && bboxRaw.every((value) => Number.isFinite(value))
      ? ([bboxRaw[0], bboxRaw[1], bboxRaw[2], bboxRaw[3]] as [
          number,
          number,
          number,
          number,
        ])
      : undefined

  const evidenceId = params.get('evidence') || undefined
  return { docId, page, bbox, evidenceId }
}