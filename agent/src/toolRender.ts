import type {
  AgentToolResult,
  Theme,
  ToolRenderers,
} from '@earendil-works/pi-coding-agent'
import { Image } from '@earendil-works/pi-tui'

import { renderSixelLines } from './terminalImage.js'

/**
 * On-brand rendering for the MBForge tools.
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

/** Word-wrap an error message so the validation tail is not silently cut. */
function wrapText(value: string, max: number): string[] {
  const single = value.replace(/\s+/g, ' ').trim()
  if (single === '') return ['']
  const lines: string[] = []
  let current = ''
  for (const word of single.split(' ')) {
    const piece = word.length > max ? `${word.slice(0, Math.max(0, max - 1))}…` : word
    if (current === '') current = piece
    else if (current.length + 1 + piece.length <= max) current += ` ${piece}`
    else {
      lines.push(current)
      current = piece
    }
  }
  if (current) lines.push(current)
  return lines
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

/** The fields the running suffix reads from a tool render context. */
interface RunningContext {
  durationMs: number | undefined
  argsComplete: boolean
  state: unknown
}

/**
 * Running suffix for a call row: `…` until the arguments are complete, then a
 * whole-second elapsed badge. The start time lives in the renderer state pi
 * shares across this row's call/result renders, so it survives each repaint.
 */
function runningSegments(theme: Theme, context: RunningContext): Segment[] {
  if (context.durationMs !== undefined) return []
  const pending: Segment[] = [
    { text: ' …', style: (value) => theme.fg('warning', value) },
  ]
  if (!context.argsComplete || !isRecord(context.state)) return pending
  const state = context.state
  const startedAt =
    typeof state.startedAt === 'number'
      ? state.startedAt
      : (state.startedAt = Date.now())
  const elapsed = Math.floor((Date.now() - startedAt) / 1000)
  return elapsed > 0
    ? [{ text: ` ${elapsed}s`, style: (value) => theme.fg('dim', value) }]
    : pending
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
  { key: 'language', render: (value) => text(value) },
  { key: 'target_path', render: (value) => `path ${clip(text(value), 40)}` },
  { key: 'query', render: (value) => `“${clip(text(value), 48)}”` },
  { key: 'title', render: (value) => `“${clip(text(value), 48)}”` },
  { key: 'content', render: (value) => `“${clip(text(value), 40)}”` },
  { key: 'instruction', render: (value) => `“${clip(text(value), 48)}”` },
  { key: 'smiles', render: (value) => `smiles ${clip(text(value), 32)}` },
  { key: 'path', render: (value) => `path ${clip(text(value).split(/[\\/]/).pop() ?? '', 32)}` },
  { key: 'doc_id', render: (value) => `doc ${shortId(value)}` },
  { key: 'run_id', render: (value) => `run ${shortId(value)}` },
  { key: 'id', render: (value) => text(value) },
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
  { key: 'summary', render: (value) => `“${clip(text(value), 40)}”` },
]

/** One-line argument summary for the built-in repository tools. */
function builtinArgs(name: string, args: JsonRecord): string {
  const path = text(args.file_path ?? args.path)
  switch (name) {
    case 'bash':
    case 'powershell': {
      const command = text(args.command)
      return command ? `$ ${clip(command, 64)}` : ''
    }
    case 'read': {
      const parts: string[] = []
      if (path) parts.push(`path ${clip(path, 40)}`)
      if (text(args.offset)) parts.push(`from ${text(args.offset)}`)
      if (text(args.limit)) parts.push(`${text(args.limit)} lines`)
      return parts.join(' · ')
    }
    case 'edit':
    case 'write':
      return path ? `path ${clip(path, 48)}` : ''
    case 'grep':
    case 'find': {
      const pattern = text(args.pattern ?? args.query)
      const parts: string[] = []
      if (pattern) parts.push(`“${clip(pattern, 40)}”`)
      if (path) parts.push(clip(path, 32))
      return parts.join(' · ')
    }
    case 'ls':
      return path ? `path ${clip(path, 48)}` : ''
    default:
      return callArgsText(args)
  }
}

/** One-line argument summary for the call row (`“query” · doc x · p3`). */
function callArgsText(args: unknown): string {
  const record = isRecord(args) ? args : {}
  const parts = ARG_HINTS.map((hint) => (text(record[hint.key]) ? hint.render(record[hint.key]) : ''))
    .filter((part) => part !== '')
  if (text(record.image_base64)) {
    const bytes = Math.round((text(record.image_base64).length * 0.75) / 1024)
    parts.unshift(`image ~${bytes}KB`)
  }
  // A capability added after this renderer still gets a readable row: show up
  // to two short scalar arguments named as stored in the schema.
  if (parts.length === 0) {
    for (const [key, value] of Object.entries(record)) {
      if (parts.length >= 2) break
      if (key === 'image_base64') continue
      if (typeof value === 'string' && value.length > 0 && value.length <= 64) {
        parts.push(`${key} ${clip(value, 32)}`)
      } else if (typeof value === 'number' || typeof value === 'boolean') {
        parts.push(`${key} ${value}`)
      }
    }
  }
  return parts.join(' · ')
}

// ------------------------------------------------------------- result summary -

/** Field that carries the primary collection for each capability shape. */
const LIST_FIELDS = ['items', 'matches', 'molecules', 'blocks', 'sections', 'entries', 'nodes', 'run_ids'] as const

/** Named collections of a report payload, in display order. */
const REPORT_LISTS: ReadonlyArray<{ field: string; singular: string; plural: string }> = [
  { field: 'lessons', singular: 'lesson', plural: 'lessons' },
  { field: 'improvements', singular: 'suggestion', plural: 'suggestions' },
  { field: 'memories', singular: 'memory note', plural: 'memory notes' },
  { field: 'warnings', singular: 'warning', plural: 'warnings' },
]

const MEMORY_LAYERS = ['hot', 'cold', 'persona'] as const

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
  if (typeof item === 'string') return clip(item, PREVIEW_CHARS)
  if (!isRecord(item)) return clip(JSON.stringify(item), PREVIEW_CHARS)
  const id = shortId(item.evidence_id ?? item.id ?? item.item_id ?? item.molecule_id ?? '')
  const page = text(item.page) ? `p${text(item.page)} · ` : ''
  const kind = text(item.kind ?? item.type ?? item.mass_check)
    ? `${text(item.kind ?? item.type ?? item.mass_check)} · `
    : ''
  const body = text(item.snippet ?? item.raw_text ?? item.text ?? item.content ?? item.smiles ?? item.esmiles ?? '')
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

/** One HTTP route row: `GET,POST /api/v1/...`, falling back to the generic line. */
function routeLine(item: unknown): string {
  const row = isRecord(item) ? item : {}
  const methods = asArray(row.methods).map((method) => text(method)).filter((method) => method !== '')
  const method = methods.length > 0 ? methods.join(',') : text(row.method)
  const path = text(row.path)
  if (method || path) return `${method ? `${method} ` : ''}${path}`.trim()
  return itemLine(item)
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

  // get_api_surface pages a route list; the count is page/total when paged.
  if (Array.isArray(data.routes)) {
    const page = data.routes.length
    const total = typeof data.total === 'number' ? data.total : page
    return {
      head: total > page ? `${page}/${total} routes` : `${page} ${page === 1 ? 'route' : 'routes'}`,
      items: data.routes.map(routeLine),
    }
  }

  // get_worker_status: queue health is a scalar payload, not a collection.
  if (
    typeof data.status === 'string' &&
    typeof data.active === 'number' &&
    typeof data.backlog === 'number'
  ) {
    const parts = [data.status === 'online' ? 'worker online' : `worker ${data.status}`]
    if (data.locked === true) parts.push('library locked')
    parts.push(`${data.active} active`, `${data.backlog} backlog`)
    if (text(data.model_gate)) parts.push(`gate ${clip(text(data.model_gate), 48)}`)
    return { head: parts.join(' · '), items: [] }
  }

  // draft: show the static check verdict, diagnostics only on expand.
  if (Array.isArray(data.checks)) {
    const checks = data.checks.filter(isRecord)
    const labels = checks.map((check) => {
      const status = text(check.status)
      const mark = status === 'ok' ? '✓' : status === 'unavailable' ? '—' : '✗'
      return `${text(check.name)} ${mark}`
    })
    const diagnostics = checks.flatMap((check) =>
      asArray(check.diagnostics).map((diagnostic) => {
        const row = isRecord(diagnostic) ? diagnostic : {}
        return `${text(check.name)} · L${text(row.line)} · ${text(row.message)}`
      }),
    )
    const saved = data.action === 'save' ? `draft ${shortId(data.id)} · ` : ''
    return { head: `${saved}${text(data.lines)} lines · ${labels.join(' · ')}`, items: diagnostics }
  }

  // ask: a decision, not a collection; show what the user chose.
  if ('cancelled' in data && text(data.kind)) {
    if (data.cancelled === true) return { head: 'cancelled', items: [] }
    const selected = asArray(data.selected)
      .map((value) => text(value))
      .filter((value) => value !== '')
    if (selected.length > 0) {
      return { head: `selected ${clip(selected.join(', '), 48)}`, items: [] }
    }
    const answer = text(data.answer_label ?? data.answer)
    return { head: answer ? `answer “${clip(answer, 48)}”` : 'answered', items: [] }
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

  // Report payloads (review_task): a prose summary plus named collections.
  if (text(data.summary)) {
    const items = text(data.summary)
      .split('\n')
      .map((line) => clip(line, PREVIEW_CHARS))
      .filter((line) => line !== '')
    const parts: string[] = []
    for (const { field, singular, plural } of REPORT_LISTS) {
      const rows = asArray(data[field])
      if (rows.length === 0) continue
      parts.push(`${rows.length} ${rows.length === 1 ? singular : plural}`)
      for (const row of rows) items.push(itemLine(row))
    }
    return { head: parts.join(' · ') || clip(text(data.summary), PREVIEW_CHARS), items }
  }

  // Goal lifecycle payloads: begin/update carry the goal record, cancel/complete the id.
  const goal = isRecord(data.goal) ? data.goal : undefined
  if (text(data.action) && (goal || text(data.goal_id))) {
    const id = text(goal?.id ?? data.goal_id)
    const title = clip(text(goal?.title ?? ''), 48)
    const queued = data.review_queued === true ? ' · review queued' : ''
    return {
      head: `goal ${text(data.action)}${id ? ` · ${shortId(id)}` : ''}${title ? ` · “${title}”` : ''}${queued}`,
      items: [],
    }
  }

  // Memory payloads: an entry action, or the active hot/cold/persona layers.
  if (text(data.entry) || typeof data.ephemeral_count === 'number') {
    const parts = [text(data.action) || 'memory']
    if (text(data.id)) parts.push(shortId(data.id))
    if (text(data.type)) parts.push(text(data.type))
    if (text(data.entry)) parts.push(`“${clip(text(data.entry), 48)}”`)
    const layers = MEMORY_LAYERS.filter((layer) => text(data[layer]))
    for (const layer of layers) parts.push(`${layer} ${text(data[layer]).length} chars`)
    if (typeof data.ephemeral_count === 'number') parts.push(`${text(data.ephemeral_count)} ephemeral`)
    const items = layers.flatMap((layer) => [
      `[${layer}]`,
      ...text(data[layer]).split('\n').map((line) => clip(line, PREVIEW_CHARS)),
    ])
    return { head: parts.join(' · '), items }
  }

  // backend_control: the message is the headline; the log path is diagnostic.
  if (
    text(data.action) &&
    text(data.base_url) &&
    'changed' in data &&
    (data.status === 'running' || data.status === 'stopped')
  ) {
    return {
      head: clip(
        text(data.message) || `${text(data.action)} · ${text(data.status)}`,
        PREVIEW_CHARS,
      ),
      items: text(data.log) ? [`log ${text(data.log)}`] : [],
    }
  }

  // Scalar-only payloads.
  if (text(data.message)) {
    return { head: clip(text(data.message), PREVIEW_CHARS), items: [] }
  }
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
 * Display-only renderers for one MBForge tool (capability or local).
 *
 * `renderShell: "self"` opts out of pi's padded, full-width background card so a
 * tool block collapses to its rows; the call is one line and the result is one
 * summary line until the user expands it. Capability results wrap their payload
 * in `details.data`; local tools keep it flat in `details`, so both are read.
 */
export function toolRenderers(name: string, mutating = false): ToolRenderers {
  return {
    renderShell: 'self',

    renderCall(args, theme, context) {
      const segments: Segment[] = [
        {
          text: `${mutating ? '⬢' : GLYPH} `,
          style: (value) => theme.fg(mutating ? 'warning' : 'accent', value),
        },
        { text: humanize(name), style: (value) => theme.bold(theme.fg('toolTitle', value)) },
      ]
      const argsText = callArgsText(args)
      if (argsText) segments.push({ text: `  ${argsText}`, style: (value) => theme.fg('dim', value) })
      segments.push(...runningSegments(theme, context))
      return {
        invalidate(): void {},
        render(width: number): string[] {
          return [renderLine(width, segments)]
        },
      }
    },

    renderResult(result, options, theme, context) {
      const image = context.showImages ? resultImage(result) : undefined
      // Terminals pi calls image-less (Windows Terminal) still draw sixel, so
      // the capability image is encoded here instead of degrading to the
      // `[Image: …]` placeholder. Kitty/iTerm2 keep pi's own component.
      const sixel = image ? renderSixelLines(image.data, image.mimeType) : null
      const imageView =
        image && !sixel
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
          const connector = (text: string) => theme.fg('borderMuted', text)
          if (context.isError === true || result.isError === true) {
            return errorResultLines(width, result, theme)
          }

          const expanded = options.expanded === true || context.expanded === true
          const summary = summarize(details.data ?? details)
          const head: Segment[] = [
            { text: '  └ ', style: connector },
            { text: '✓ ', style: (value) => theme.fg('success', value) },
            { text: `${summary.head}${truncationFlag(details)}`, style: (value) => theme.fg('muted', value) },
          ]
          const duration = formatDuration(context.durationMs)
          if (duration) head.push({ text: ` · ${duration}`, style: (value) => theme.fg('dim', value) })

          if (!expanded && summary.items.length > 0) {
            const key = context.keyHint?.('app.tools.expand', 'expand') ?? 'expand'
            head.push({ text: ` · ▾ ${key}`, style: (value) => theme.fg('dim', value) })
          }

          const lines = [renderLine(width, head)]
          if (sixel) lines.push(...sixel.lines)
          else if (imageView) lines.push(...imageView.render(width))
          if (!expanded) return lines

          const shown = summary.items.slice(0, EXPANDED_ITEMS)
          const hidden = summary.items.length - shown.length
          for (const item of shown) {
            lines.push(renderLine(width, [{ text: item, style: (value) => theme.fg('toolOutput', value) }], 6))
          }
          if (hidden > 0) {
            lines.push(renderLine(width, [{ text: `… ${hidden} more`, style: (value) => theme.fg('dim', value) }], 6))
          }
          return lines
        },
      }
    },
  }
}

/**
 * Restyle a built-in tool's call row while keeping pi's result renderer.
 *
 * Built-ins own rich result views (diffs, bash tails, read ranges); replacing
 * those would lose information. Only the one-line call row changes, so dev-mode
 * repository work uses the same `⬡ name args` grammar as capability calls.
 */
export function builtinToolRenderers(name: string, base: ToolRenderers): ToolRenderers {
  return {
    ...base,
    renderCall(args, theme, context) {
      const record = isRecord(args) ? args : {}
      const segments: Segment[] = [
        { text: `${GLYPH} `, style: (value) => theme.fg('accent', value) },
        { text: humanize(name), style: (value) => theme.bold(theme.fg('toolTitle', value)) },
      ]
      const detail = builtinArgs(name, record)
      if (detail) segments.push({ text: `  ${detail}`, style: (value) => theme.fg('dim', value) })
      segments.push(...runningSegments(theme, context))
      return {
        invalidate(): void {},
        render(width: number): string[] {
          return [renderLine(width, segments)]
        },
      }
    },
  }
}

function truncationFlag(details: ResultDetails): string {
  if (typeof details.next_offset === 'number') return ` · more at offset ${details.next_offset}`
  return details.truncated ? ' · truncated' : ''
}

function errorText(result: AgentToolResult<unknown>): string {
  const joined = (result.content ?? [])
    .map((part) => ('text' in part ? text(part.text) : ''))
    .filter((value) => value !== '')
    .join(' ')
  return joined || 'capability failed'
}

/** A failed call: connector + ✗ on the first wrapped line, indented continuation. */
function errorResultLines(
  width: number,
  result: AgentToolResult<unknown>,
  theme: Theme,
): string[] {
  const errorStyle = (value: string) => theme.fg('error', value)
  const all = wrapText(errorText(result), Math.max(20, width - 8))
  const shown = all.slice(0, 3)
  const lines = shown.map((line, index) =>
    index === 0
      ? renderLine(width, [
          { text: '  └ ', style: (value) => theme.fg('borderMuted', value) },
          { text: '✗ ', style: errorStyle },
          { text: line, style: errorStyle },
        ])
      : renderLine(width, [{ text: line, style: errorStyle }], 6),
  )
  if (shown.length < all.length) {
    lines.push(renderLine(width, [{ text: '…', style: (value) => theme.fg('dim', value) }], 6))
  }
  return lines
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

// ---------------------------------------------------------- improvement tool --

// Field labels mirror the approval dialog (formatImprovementPrompt) so the
// transcript expansion reads like the confirmation the user answered.
const IMPROVEMENT_FIELDS: ReadonlyArray<{ key: string; label: string }> = [
  { key: 'problem', label: '问题' },
  { key: 'change', label: '改动' },
  { key: 'rationale', label: '收益' },
  { key: 'risk', label: '风险' },
]

interface ImprovementLine {
  text: string
  indent: number
  label?: boolean
}

function improvementItemLine(item: unknown): string {
  const row = isRecord(item) ? item : {}
  const status = text(row.status)
  const mark = status === 'approved' ? '✓' : status === 'implemented' ? '●' : '×'
  const label = status === 'rejected' ? 'declined' : status
  const area = text(row.area)
  const title = clip(text(row.title), 48)
  return `${mark} ${text(row.id)}  ${area ? `${area} · ` : ''}${title}${label ? ` · ${label}` : ''}`
}

/** Expanded rows: the proposal body for propose, the log for list, the note for complete. */
function improvementDetailLines(details: JsonRecord, args: JsonRecord): ImprovementLine[] {
  const action = text(details.action)
  if (action === 'propose') {
    const lines: ImprovementLine[] = []
    for (const { key, label } of IMPROVEMENT_FIELDS) {
      const value = text(args[key])
      if (!value) continue
      lines.push({ text: label, indent: 2, label: true })
      for (const part of value.split('\n')) {
        lines.push({ text: clip(part, PREVIEW_CHARS), indent: 4 })
      }
    }
    const files = asArray(args.files).map((file) => text(file)).filter((file) => file !== '')
    if (files.length > 0) {
      lines.push({ text: '涉及', indent: 2, label: true })
      for (const file of files) lines.push({ text: clip(file, PREVIEW_CHARS), indent: 4 })
    }
    return lines
  }
  if (action === 'list') {
    return asArray(details.items).map((item) => ({ text: improvementItemLine(item), indent: 2 }))
  }
  if (action === 'complete') {
    const note = text(args.note)
    return note ? [{ text: clip(note, PREVIEW_CHARS), indent: 2 }] : []
  }
  return []
}

/**
 * Display-only renderers for `suggest_improvement`.
 *
 * The call row names the action and the proposal title instead of dumping the
 * full argument JSON; the result row states the decision (approved / declined
 * / implemented) and expands to the proposal body or the suggestion log. The
 * model-facing payload is untouched.
 */
export function improvementRenderers(): ToolRenderers {
  return {
    renderShell: 'self',

    renderCall(args, theme, context) {
      const record = isRecord(args) ? args : {}
      const action = text(record.action)
      const segments: Segment[] = [
        { text: `${GLYPH} `, style: (value) => theme.fg('accent', value) },
        { text: 'suggest improvement', style: (value) => theme.bold(theme.fg('toolTitle', value)) },
      ]
      const parts: string[] = []
      if (action) parts.push(action)
      if (action === 'propose') {
        if (text(record.area)) parts.push(text(record.area))
        if (text(record.title)) parts.push(`“${clip(text(record.title), 48)}”`)
      } else if (action === 'complete') {
        if (text(record.id)) parts.push(text(record.id))
        if (text(record.note)) parts.push(`“${clip(text(record.note), 32)}”`)
      }
      if (parts.length > 0) {
        segments.push({ text: `  ${parts.join(' · ')}`, style: (value) => theme.fg('dim', value) })
      }
      segments.push(...runningSegments(theme, context))
      return {
        invalidate(): void {},
        render(width: number): string[] {
          return [renderLine(width, segments)]
        },
      }
    },

    renderResult(result, options, theme, context) {
      return {
        invalidate(): void {},
        render(width: number): string[] {
          const connector = (text: string) => theme.fg('borderMuted', text)
          if (context.isError === true || result.isError === true) {
            return errorResultLines(width, result, theme)
          }

          const details = isRecord(result.details) ? result.details : {}
          const args = isRecord(context.args) ? context.args : {}
          const action = text(details.action)
          const head: Segment[] = [{ text: '  └ ', style: connector }]
          const notices: Segment[][] = []
          if (action === 'propose') {
            const approved = details.approved === true
            const title = clip(text(args.title), 48)
            head.push(
              approved
                ? { text: '✓ approved', style: (value) => theme.fg('success', value) }
                : { text: '× declined', style: (value) => theme.fg('muted', value) },
            )
            head.push({
              text: ` · ${text(details.id)}${title ? ` · “${title}”` : ''}`,
              style: (value) => theme.fg('muted', value),
            })
            if (approved && details.executable !== true) {
              notices.push([
                { text: '    ! ', style: (value) => theme.fg('warning', value) },
                { text: 'dev mode required', style: (value) => theme.fg('warning', value) },
              ])
            }
          } else if (action === 'list') {
            const items = asArray(details.items)
            head.push({ text: '✓ ', style: (value) => theme.fg('success', value) })
            if (items.length === 0) {
              head.push({ text: 'no suggestions', style: (value) => theme.fg('muted', value) })
            } else {
              let approved = 0
              let implemented = 0
              let declined = 0
              for (const item of items) {
                const status = text(isRecord(item) ? item.status : '')
                if (status === 'approved') approved += 1
                else if (status === 'implemented') implemented += 1
                else if (status === 'rejected') declined += 1
              }
              const parts = [`${items.length} suggestions`]
              if (approved > 0) parts.push(`${approved} approved`)
              if (implemented > 0) parts.push(`${implemented} implemented`)
              if (declined > 0) parts.push(`${declined} declined`)
              head.push({ text: parts.join(' · '), style: (value) => theme.fg('muted', value) })
            }
          } else if (action === 'complete') {
            const already = details.already_completed === true
            head.push({ text: '✓ ', style: (value) => theme.fg('success', value) })
            head.push({
              text: `${already ? 'already implemented' : 'implemented'} · ${text(details.id)}`,
              style: (value) => theme.fg('muted', value),
            })
          } else {
            head.push({ text: '✓ ok', style: (value) => theme.fg('muted', value) })
          }

          const duration = formatDuration(context.durationMs)
          if (duration) head.push({ text: ` · ${duration}`, style: (value) => theme.fg('dim', value) })

          const detailLines = improvementDetailLines(details, args)
          const expanded = options.expanded === true || context.expanded === true
          if (!expanded && detailLines.length > 0) {
            const key = context.keyHint?.('app.tools.expand', 'expand') ?? 'expand'
            head.push({ text: ` · ▾ ${key}`, style: (value) => theme.fg('dim', value) })
          }

          const lines = [renderLine(width, head)]
          for (const notice of notices) lines.push(renderLine(width, notice))
          if (!expanded) return lines

          const shown = detailLines.slice(0, EXPANDED_ITEMS)
          for (const line of shown) {
            lines.push(
              renderLine(
                width,
                [{ text: line.text, style: (value) => theme.fg(line.label ? 'dim' : 'toolOutput', value) }],
                line.indent + 4,
              ),
            )
          }
          const hidden = detailLines.length - shown.length
          if (hidden > 0) {
            lines.push(renderLine(width, [{ text: `… ${hidden} more`, style: (value) => theme.fg('dim', value) }], 6))
          }
          return lines
        },
      }
    },
  }
}
