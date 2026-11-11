import type { AgentToolResult, ToolRenderers } from '@earendil-works/pi-coding-agent'
import { Image } from '@earendil-works/pi-tui'

/**
 * On-brand rendering for the MBForge capability tools.
 *
 * Without these hooks pi draws every call as `tool_name {json args}` and every
 * result as a raw JSON dump. The renderers here keep the model-facing payload
 * untouched (they are display-only) and instead show a readable title plus a
 * derived summary, a one-line-per-item preview when collapsed, and the full
 * item list when the user expands the row.
 */

const GLYPH = '⬡'
// A collapsed tool block is a single line; only the expanded view lists items.
const EXPANDED_ITEMS = 40
const PREVIEW_CHARS = 72

interface JsonRecord {
  [key: string]: unknown
}

interface ResultDetails {
  data?: unknown
  truncated?: boolean
  next_offset?: number | null
  evidenceIndex?: unknown
}

// ---------------------------------------------------------------- primitives --

function isRecord(value: unknown): value is JsonRecord {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function asArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : []
}

function text(value: unknown): string {
  if (typeof value === 'string') return value
  if (typeof value === 'number' || typeof value === 'boolean') return String(value)
  return ''
}

function shortId(value: unknown): string {
  const id = text(value)
  return id.length > 12 ? `${id.slice(0, 10)}…` : id
}

function clip(value: string, max: number): string {
  const single = value.replace(/\s+/g, ' ').trim()
  return single.length > max ? `${single.slice(0, max - 1)}…` : single
}

/** Truncate to visible width without collapsing whitespace, so inter-segment
 *  padding and separators survive; content already runs through `clip`. */
function fit(value: string, max: number): string {
  return value.length > max ? `${value.slice(0, Math.max(0, max - 1))}…` : value
}

function formatDuration(ms: number | undefined): string {
  if (ms === undefined) return ''
  return ms < 1000 ? `${Math.round(ms)}ms` : `${(ms / 1000).toFixed(1)}s`
}

/** A piece of a status line together with the style that colours it. */
interface Segment {
  text: string
  style?: ((value: string) => string) | undefined
}

/**
 * Join segments into one row no wider than `width` visible columns. Plain text
 * is truncated before styling so ANSI escapes never count toward the width.
 * `indent` nests a row under its header (used for expanded item lines).
 */
function renderLine(width: number, segments: Segment[], indent = 0): string {
  const pad = ' '.repeat(indent)
  let remaining = Math.max(0, width - indent)
  let output = ''
  for (const segment of segments) {
    if (remaining <= 0) break
    const value = fit(segment.text, remaining)
    remaining -= value.length
    output += segment.style ? segment.style(value) : value
  }
  return `${pad}${output}`
}

// ------------------------------------------------------------------- titles ---

/** `search_evidence` reads better as `search evidence` than as a code symbol. */
function humanize(name: string): string {
  return name.replaceAll('_', ' ')
}

// ---------------------------------------------------------------- call line -

const ARG_HINTS: ReadonlyArray<{ key: string; render: (value: unknown) => string }> = [
  { key: 'action', render: (value) => text(value) },
  { key: 'query', render: (value) => `“${clip(text(value), 48)}”` },
  { key: 'smiles', render: (value) => `smiles ${clip(text(value), 32)}` },
  { key: 'path', render: (value) => `path ${clip(text(value).split(/[\\/]/).pop() ?? '', 32)}` },
  { key: 'doc_id', render: (value) => `doc ${shortId(value)}` },
  { key: 'run_id', render: (value) => `run ${shortId(value)}` },
  { key: 'page', render: (value) => `p${text(value)}` },
  {
    key: 'region',
    render: (value) => `[${asArray(value).map((edge) => Math.round(Number(edge))).join(',')}]`,
  },
  { key: 'kind', render: (value) => text(value) },
  { key: 'mode', render: (value) => text(value) },
  { key: 'top_k', render: (value) => `top ${text(value)}` },
  { key: 'max_molecules', render: (value) => `max ${text(value)}` },
  { key: 'limit', render: (value) => `limit ${text(value)}` },
]

/** One-line argument summary for the call row (`“query” · doc x · p3`). */
function callArgsText(args: unknown): string {
  const record = isRecord(args) ? args : {}
  const parts = ARG_HINTS.map((hint) => (text(record[hint.key]) ? hint.render(record[hint.key]) : ''))
    .filter((part) => part !== '')
  if (text(record.image_base64)) {
    const bytes = Math.round((text(record.image_base64).length * 0.75) / 1024)
    parts.unshift(`image ~${bytes}KB`)
  }
  return parts.join(' · ')
}

// ------------------------------------------------------------- result summary -

/** Field that carries the primary collection for each capability shape. */
const LIST_FIELDS = ['items', 'matches', 'molecules', 'blocks', 'sections', 'entries', 'nodes', 'run_ids'] as const

function nounFor(field: string, sample: unknown): string {
  if (field === 'matches') return 'documents'
  if (field === 'molecules') return 'molecules'
  if (field === 'blocks') return 'text blocks'
  if (field === 'sections') return 'sections'
  if (field === 'entries') return 'entries'
  if (field === 'nodes') return 'stages'
  if (field === 'run_ids') return 'runs'
  const row = isRecord(sample) ? sample : {}
  if ('mass_check' in row) return 'structures'
  if ('evidence_id' in row || 'snippet' in row) return 'evidence'
  if ('item_id' in row) return 'review items'
  if ('smiles' in row) return 'molecules'
  if ('stage' in row) return 'stages'
  return 'results'
}

/** One readable line for a collection row, chosen from its actual fields. */
function itemLine(item: unknown): string {
  if (!isRecord(item)) return clip(JSON.stringify(item), PREVIEW_CHARS)
  const id = shortId(item.evidence_id ?? item.id ?? item.item_id ?? item.molecule_id ?? '')
  const page = text(item.page) ? `p${text(item.page)} · ` : ''
  const kind = text(item.kind ?? item.type ?? item.mass_check)
    ? `${text(item.kind ?? item.type ?? item.mass_check)} · `
    : ''
  const body = text(item.snippet ?? item.raw_text ?? item.text ?? item.smiles ?? item.esmiles ?? '')
  const labelKeys = asArray(item.label_keys)
  const title =
    text(item.title ?? item.name ?? item.label) ||
    (labelKeys.length > 0 ? text(labelKeys[0]) : '')
  if (text(item.stage)) return `${text(item.stage)} → ${text(item.status)}`
  const head = title || id
  if (body) return `${page}${kind}${head ? `${head} · ` : ''}“${clip(body, PREVIEW_CHARS)}”`
  if (text(item.status)) return `${head || '·'} · ${text(item.status)}`
  if (head) return `${page}${kind}${head}`
  return clip(JSON.stringify(item), PREVIEW_CHARS)
}

interface Summary {
  head: string
  items: string[]
}

/** Derive a header phrase and per-item lines from a capability output payload. */
function summarize(data: unknown): Summary {
  if (data === null || data === undefined) return { head: 'no data', items: [] }
  if (Array.isArray(data)) {
    const noun = nounFor('items', data[0])
    return { head: `${data.length} ${noun}`, items: data.map(itemLine) }
  }
  if (!isRecord(data)) return { head: clip(text(data), PREVIEW_CHARS), items: [] }

  // A Patent facts summary answers with counts and an empty items array; the
  // list branch below would otherwise read that as "no items".
  const counts = isRecord(data.counts) ? data.counts : undefined
  if (counts) {
    const parts = Object.entries(counts)
      .filter(([, value]) => typeof value === 'number' && (value as number) > 0)
      .map(([key, value]) => `${humanize(key)} ${text(value)}`)
    return { head: parts.join(' · ') || 'patent facts', items: [] }
  }

  for (const field of LIST_FIELDS) {
    if (!(field in data)) continue
    const rows = asArray(data[field])
    if (rows.length === 0) {
      return { head: `no ${nounFor(field, {})}`, items: [] }
    }
    if (field === 'run_ids') {
      return { head: `${rows.length} runs`, items: rows.map((run) => `run ${shortId(run)}`) }
    }
    return { head: `${rows.length} ${nounFor(field, rows[0])}`, items: rows.map(itemLine) }
  }

  // Scalar-only payloads.
  if (text(data.content)) {
    const content = text(data.content)
    const lines = content.split('\n').slice(0, EXPANDED_ITEMS).map((value) => clip(value, PREVIEW_CHARS))
    return { head: `${content.length} chars`, items: lines }
  }
  if (text(data.smiles) || text(data.esmiles)) {
    const recognized = data.recognized === false ? ' · not recognized' : ''
    const primary = text(data.coref_primary ?? data.smiles)
    return { head: `SMILES ${clip(primary, PREVIEW_CHARS)}${recognized}`, items: [] }
  }
  if (text(data.page) && text(data.width) && text(data.height)) {
    const doc = text(data.doc_id) ? `${shortId(data.doc_id)} · ` : ''
    return {
      head: `${doc}p${text(data.page)} · ${text(data.width)}×${text(data.height)}`,
      items: [],
    }
  }
  if (text(data.title) || text(data.doc_id)) {
    const status = text(data.status) ? ` · ${text(data.status)}` : ''
    const pages = text(data.page_count) ? ` · ${text(data.page_count)}p` : ''
    const title = text(data.title) || shortId(data.doc_id)
    return { head: `${clip(title, 48)}${status}${pages}`, items: [] }
  }
  if (text(data.enqueued) || text(data.skipped)) {
    return { head: `${text(data.enqueued)} enqueued · ${text(data.skipped)} skipped`, items: [] }
  }
  if (text(data.updated)) return { head: `${text(data.updated)} updated`, items: [] }
  if (text(data.run_id)) return { head: `run ${shortId(data.run_id)}`, items: [] }
  return { head: 'ok', items: [] }
}

// ------------------------------------------------------------------ exports --

/**
 * Display-only renderers for one capability tool.
 *
 * `renderShell: "self"` opts out of pi's padded, full-width background card so a
 * tool block collapses to its rows; the call is one line and the result is one
 * summary line until the user expands it.
 */
export function capabilityRenderers(name: string): ToolRenderers {
  return {
    renderShell: 'self',

    renderCall(args, theme, context) {
      const segments: Segment[] = [
        { text: `${GLYPH} `, style: (value) => theme.fg('accent', value) },
        { text: humanize(name), style: (value) => theme.bold(theme.fg('toolTitle', value)) },
      ]
      const argsText = callArgsText(args)
      if (argsText) segments.push({ text: `  ${argsText}`, style: (value) => theme.fg('dim', value) })
      if (context.durationMs === undefined) {
        segments.push({ text: ' …', style: (value) => theme.fg('warning', value) })
      }
      return {
        invalidate(): void {},
        render(width: number): string[] {
          return [renderLine(width, segments)]
        },
      }
    },

    renderResult(result, options, theme, context) {
      const image = context.showImages ? resultImage(result) : undefined
      const imageView = image
        ? new Image(
            image.data,
            image.mimeType,
            { fallbackColor: (value) => theme.fg('dim', value) },
            { maxWidthCells: 72, maxHeightCells: 24 },
          )
        : undefined
      return {
        invalidate(): void {
          imageView?.invalidate()
        },
        render(width: number): string[] {
          const details = (result.details ?? {}) as ResultDetails
          if (context.isError === true || result.isError === true) {
            return [
              renderLine(width, [
                { text: '✗ ', style: (value) => theme.fg('error', value) },
                { text: clip(errorText(result), PREVIEW_CHARS * 2), style: (value) => theme.fg('error', value) },
              ]),
            ]
          }

          const expanded = options.expanded === true || context.expanded === true
          const summary = summarize(details.data)
          const head: Segment[] = [
            { text: '✓ ', style: (value) => theme.fg('success', value) },
            { text: `${summary.head}${truncationFlag(details)}`, style: (value) => theme.fg('muted', value) },
          ]
          const duration = formatDuration(context.durationMs)
          if (duration) head.push({ text: ` ${duration}`, style: (value) => theme.fg('dim', value) })

          if (!expanded && summary.items.length > 0) {
            const key = context.keyHint?.('app.tools.expand', 'expand') ?? 'expand'
            head.push({ text: `  ▾ ${key}`, style: (value) => theme.fg('dim', value) })
          }

          const lines = [renderLine(width, head)]
          if (imageView) lines.push(...imageView.render(width))
          if (!expanded) return lines

          const shown = summary.items.slice(0, EXPANDED_ITEMS)
          const hidden = summary.items.length - shown.length
          for (const item of shown) {
            lines.push(renderLine(width, [{ text: item, style: (value) => theme.fg('toolOutput', value) }], 2))
          }
          if (hidden > 0) {
            lines.push(renderLine(width, [{ text: `… ${hidden} more`, style: (value) => theme.fg('dim', value) }], 2))
          }
          return lines
        },
      }
    },
  }
}

function truncationFlag(details: ResultDetails): string {
  if (typeof details.next_offset === 'number') return ` · more → ${details.next_offset}`
  return details.truncated ? ' · truncated' : ''
}

function errorText(result: AgentToolResult<unknown>): string {
  const joined = (result.content ?? [])
    .map((part) => ('text' in part ? text(part.text) : ''))
    .filter((value) => value !== '')
    .join(' ')
  return joined || 'capability failed'
}

/** The rendered image block, if the capability returned one. */
function resultImage(
  result: AgentToolResult<unknown>,
): { data: string; mimeType: string } | undefined {
  for (const part of result.content ?? []) {
    if (part.type === 'image') return part
  }
  return undefined
}
