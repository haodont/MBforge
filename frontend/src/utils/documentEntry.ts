import type { DocumentEntry } from '@/types'

/**
 * Minimal entry for opening a document by id.
 *
 * The viewer loads the PDF through the doc-id endpoint; `path` is only a
 * display/legacy fallback, so the legacy `source.pdf` name is kept.
 */
export function documentEntry(docId: string): DocumentEntry {
  const path = `storage/${docId}/source.pdf`
  return {
    doc_id: docId,
    path,
    source_path: path,
    doc_type: 'pdf',
    title: docId,
    added_at: new Date().toISOString(),
    hash: '',
  }
}
