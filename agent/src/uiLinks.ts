/**
 * Web-workbench links for the agent CLI.
 *
 * The terminal can quote a value but cannot show the page region, the drawing,
 * or the review queue around it. The model therefore never assembles a URL: it
 * writes an opaque `[[ui:...]]` marker naming a workbench surface, and this
 * module turns the marker into a markdown link whose base URL and encoding come
 * from here. Pi draws that link as a clickable OSC 8 hyperlink, so the user can
 * jump straight to the evidence or the pending decision in the browser.
 */

import { frontendBaseUrl } from './citations.js'

/**
 * Review kinds the review center accepts, mirroring ``ReviewKind`` in
 * ``service/dto/review.py``. An unknown kind keeps the marker literal instead
 * of linking a route the menu would silently rewrite.
 */
const REVIEW_KINDS: Record<string, true> = {
  low_conf_molecule: true,
  review_required: true,
  unparsable_smiles: true,
  missing_evidence: true,
  ambiguous_coref: true,
  smiles_correction: true,
  ai_review: true,
  designation_unbound: true,
}

const FULL_DOC_ID = /^[0-9a-fA-F]{64}$/

/** A document tab at an optional page (`/open?doc=&page=`). */
export function documentUrl(docId: string, page?: number): string {
  const params = new URLSearchParams({ doc: docId })
  if (page !== undefined) params.set('page', String(page))
  return `${frontendBaseUrl()}/open?${params.toString()}`
}

/** The whole review queue (`/review`). */
export function reviewQueueUrl(): string {
  return `${frontendBaseUrl()}/review`
}

/** One queue item, addressed exactly as the review center seeds selection. */
export function reviewItemUrl(kind: string, itemId: string): string {
  const params = new URLSearchParams({ kind, id: itemId })
  return `${frontendBaseUrl()}/review?${params.toString()}`
}

/** A workbench page with no item parameter. */
export function workbenchUrl(path: string): string {
  return `${frontendBaseUrl()}${path}`
}

const UI_MARKER = /\[\[ui:([a-z]+)(?::([^\]\s]+))?\]\]/g

function link(label: string, url: string): string {
  return `[${label}](${url})`
}

/**
 * Render `[[ui:...]]` markers as markdown links; an unknown or malformed
 * marker stays literal rather than fabricating a route.
 *
 * `[[ui:review]]`, `[[ui:review:<kind>:<item_id>]]`,
 * `[[ui:doc:<doc_id>]]`, `[[ui:doc:<doc_id>:<page>]]`,
 * `[[ui:queue]]`, `[[ui:molecules]]`, `[[ui:workspace]]`.
 */
export function linkifyUiLinks(markdown: string): string {
  return markdown.replace(UI_MARKER, (marker: string, name: string, rest?: string) => {
    switch (name) {
      case 'review': {
        if (rest === undefined) return link('复核中心', reviewQueueUrl())
        const separator = rest.indexOf(':')
        if (separator <= 0) return marker
        const kind = rest.slice(0, separator)
        const itemId = rest.slice(separator + 1)
        if (REVIEW_KINDS[kind] !== true || itemId === '') return marker
        return link('复核项', reviewItemUrl(kind, itemId))
      }
      case 'doc': {
        if (rest === undefined) return marker
        const parts = rest.split(':')
        if (parts.length > 2) return marker
        const [docId, pageText] = parts
        if (!FULL_DOC_ID.test(docId)) return marker
        if (pageText === undefined) return link('文档', documentUrl(docId))
        const page = Number(pageText)
        if (!Number.isInteger(page) || page < 1) return marker
        return link(`文档·p.${page}`, documentUrl(docId, page))
      }
      case 'queue':
        return rest === undefined ? link('处理队列', workbenchUrl('/queue')) : marker
      case 'molecules':
        return rest === undefined ? link('分子库', workbenchUrl('/molecules')) : marker
      case 'workspace':
        return rest === undefined ? link('工作台', workbenchUrl('/workspace')) : marker
      default:
        return marker
    }
  })
}

/** Tools whose results the user should inspect in the browser, not only read. */
const DOC_LINK_TOOLS: Record<string, true> = {
  document_read: true,
  list_evidence: true,
  verify_structures: true,
  get_patent_result: true,
  query_activities: true,
  inspect_visual: true,
}
const RUN_LINK_TOOLS: Record<string, true> = {
  import_pdf: true,
  submit_extraction: true,
  submit_patent_analysis: true,
  reingest_document: true,
}

/**
 * Tell the model which markers the results of *toolName* can be linked with.
 * Absent for tools whose rows are not worth a workbench jump.
 */
export function uiGuidelines(toolName: string): string[] | undefined {
  if (toolName === 'list_review_queue') {
    return [
      'A pending review item is a human decision, not something you may apply. ' +
        'When you name one, address the same item in the review center by writing ' +
        '[[ui:review:<kind>:<item_id>]] with the exact kind and item_id from this ' +
        'result, and point at the queue with [[ui:review]]. Never write the URL ' +
        'yourself: the workbench builds and encodes it from the marker.',
    ]
  }
  if (DOC_LINK_TOOLS[toolName] === true) {
    return [
      'When the user should look at the page rather than only read your summary, ' +
        'offer a document link as [[ui:doc:<doc_id>]] or, at a page, ' +
        '[[ui:doc:<doc_id>:<page>]], using the full doc_id from this result. ' +
        'Never write the URL yourself.',
    ]
  }
  if (RUN_LINK_TOOLS[toolName] === true) {
    return [
      'Report the returned run id and, when the user will want to watch it, ' +
        'point at the processing queue with [[ui:queue]]. Never write the URL ' +
        'yourself.',
    ]
  }
  if (toolName === 'search_molecules') {
    return [
      'When the user wants to browse or compare the structures in the workbench, ' +
        'point at the molecule library with [[ui:molecules]]. Never write the URL ' +
        'yourself.',
    ]
  }
  return undefined
}
