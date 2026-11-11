/** Length of the doc_id prefix shown to people. */
export const DOC_ID_DISPLAY_LENGTH = 12

/**
 * Show a content-addressed doc_id as its short, quotable prefix.
 *
 * The full SHA-256 stays the stored key; this is display only. The backend
 * accepts any unique prefix of 8+ hex characters, so a 12-character form is
 * always resolvable unless two documents collide in those 12 characters.
 */
export function shortDocId(docId: string): string {
  return docId.length > DOC_ID_DISPLAY_LENGTH
    ? docId.slice(0, DOC_ID_DISPLAY_LENGTH)
    : docId
}

/** The human label for a document: its title, or the short doc_id. */
export function documentLabel(document: {
  doc_id: string
  title?: string
}): string {
  return document.title?.trim() || shortDocId(document.doc_id)
}
