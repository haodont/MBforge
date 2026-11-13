import type { Component } from '@earendil-works/pi-tui'
import type {
  MessageRenderOptions,
  Theme,
  ThemeColor,
} from '@earendil-works/pi-coding-agent'

import {
  countLabel,
  joinColumns,
  renderRow,
  wrapText,
  type Segment,
} from './uiText.js'
import { asArray, clip, isRecord } from './text.js'

/**
 * Branded rendering for the background goal-review report.
 *
 * The report is injected as a custom message, so pi's default rendering would
 * show a purple `[mbforge-goal-review]` box with the whole markdown body. This
 * card keeps the same information in the transcript's own grammar: one header
 * row with the goal id and outcome, a wrapped summary, a count line, and the
 * suggestions/warnings only when the row is expanded.
 */

export const GOAL_REVIEW_MESSAGE_TYPE = 'mbforge-goal-review'
export const RUN_MESSAGE_TYPE = 'mbforge.run'

const GLYPH = '⬡'
/** Collapsed reports stay short; the whole summary is one keypress away. */
const COLLAPSED_SUMMARY_LINES = 4
const MAX_EXPANDED_ITEMS = 12

const RUN_STATUS_COLORS: Readonly<Record<string, ThemeColor>> = {
  done: 'success',
  failed: 'error',
  cancelled: 'warning',
}

interface GoalReviewDetails {
  goalId?: unknown
  summary?: unknown
  memories?: unknown
  improvements?: unknown
  warnings?: unknown
  error?: unknown
}

/** The fields this renderer reads from a custom message. */
interface RenderableMessage {
  content:
    | string
    | ReadonlyArray<{ type?: string | undefined; text?: string | undefined }>
  details?: unknown
}

function asText(value: unknown): string {
  return typeof value === 'string' ? value : ''
}

/** A suggestion/warning row: a string, or an object with a title/message. */
function itemText(item: unknown): string {
  if (typeof item === 'string') return item
  if (!isRecord(item)) return ''
  return asText(item.title) || asText(item.message) || asText(item.text)
}

function messageText(message: RenderableMessage): string {
  if (typeof message.content === 'string') return message.content
  return message.content
    .filter((part) => part.type === 'text')
    .map((part) => part.text ?? '')
    .join('\n')
}

/**
 * Render one `mbforge-goal-review` custom message. The details payload is
 * authoritative; a session persisted before the details shape existed falls
 * back to the message content.
 */
export function goalReviewRenderer(
  message: RenderableMessage,
  options: MessageRenderOptions,
  theme: Theme,
): Component {
  return {
    invalidate(): void {},
    render(width: number): string[] {
      const pad = ' '.repeat(Math.max(0, options.outputPad))
      const usable = Math.max(12, width - pad.length)
      const details = isRecord(message.details)
        ? (message.details as GoalReviewDetails)
        : undefined
      const error = asText(details?.error)
      const goalId = asText(details?.goalId)
      const summary = asText(details?.summary) || messageText(message)
      const memories = asArray(details?.memories)
      const improvements = asArray(details?.improvements)
      const warnings = asArray(details?.warnings)

      const title: Segment[] = [
        { text: `${GLYPH} `, style: (text) => theme.fg('accent', text) },
        {
          text: 'goal review',
          style: (text) => theme.bold(theme.fg('customMessageLabel', text)),
        },
      ]
      if (goalId) {
        title.push({
          text: ` · ${clip(goalId, 28)}`,
          style: (text) => theme.fg('dim', text),
        })
      }
      const outcome: Segment[] = error
        ? [{ text: '✗ failed', style: (text) => theme.fg('error', text) }]
        : [{ text: '✓ completed', style: (text) => theme.fg('success', text) }]
      const lines = [renderRow(usable, joinColumns(title, outcome, usable))]

      if (error) {
        for (const line of wrapText(error, usable - 2)) {
          lines.push(
            renderRow(usable, [
              { text: `  ${line}`, style: (text) => theme.fg('error', text) },
            ]),
          )
        }
        return lines.map((line) => `${pad}${line}`)
      }

      const summaryLines = wrapText(summary, usable - 2)
      const visibleSummary = options.expanded
        ? summaryLines
        : summaryLines.slice(0, COLLAPSED_SUMMARY_LINES)
      for (const line of visibleSummary) {
        if (line === '') {
          lines.push('')
          continue
        }
        lines.push(
          renderRow(usable, [
            { text: `  ${line}`, style: (text) => theme.fg('text', text) },
          ]),
        )
      }
      const hiddenSummary = summaryLines.length - visibleSummary.length

      const counts: string[] = []
      if (memories.length > 0)
        counts.push(
          countLabel(memories.length, 'memory lesson', 'memory lessons'),
        )
      if (improvements.length > 0)
        counts.push(
          countLabel(improvements.length, 'suggestion', 'suggestions'),
        )
      if (warnings.length > 0)
        counts.push(countLabel(warnings.length, 'warning', 'warnings'))
      if (counts.length > 0) {
        lines.push(
          renderRow(usable, [
            {
              text: `  ${counts.join(' · ')}`,
              style: (text) => theme.fg('muted', text),
            },
          ]),
        )
      }

      const detailsAvailable =
        hiddenSummary > 0 || improvements.length > 0 || warnings.length > 0
      if (!options.expanded) {
        if (detailsAvailable) {
          const hint = options.keyHint('app.tools.expand', 'expand')
          lines.push(
            renderRow(usable, [
              { text: `  › ${hint}`, style: (text) => theme.fg('dim', text) },
            ]),
          )
        }
      } else {
        if (improvements.length > 0) {
          lines.push(
            renderRow(usable, [
              { text: '  suggestions', style: (text) => theme.fg('dim', text) },
            ]),
          )
          for (const item of improvements.slice(0, MAX_EXPANDED_ITEMS)) {
            lines.push(
              renderRow(usable, [
                { text: '   • ', style: (text) => theme.fg('accent', text) },
                {
                  text: clip(itemText(item), usable - 8),
                  style: (text) => theme.fg('text', text),
                },
              ]),
            )
          }
        }
        if (warnings.length > 0) {
          lines.push(
            renderRow(usable, [
              { text: '  warnings', style: (text) => theme.fg('dim', text) },
            ]),
          )
          for (const item of warnings.slice(0, MAX_EXPANDED_ITEMS)) {
            lines.push(
              renderRow(usable, [
                { text: '   ! ', style: (text) => theme.fg('warning', text) },
                {
                  text: clip(itemText(item), usable - 8),
                  style: (text) => theme.fg('warning', text),
                },
              ]),
            )
          }
        }
      }

      return lines.map((line) => `${pad}${line}`)
    },
  }
}

/**
 * Render an `mbforge.run` completion notice. The details carry one entry per
 * run and the content carries the per-run message; the header is rebuilt from
 * details and only the message body (stages, failures, next step) is shown
 * under it, so a finished pipeline reads like a transcript event rather than a
 * purple custom-message box.
 */
export function runNoticeRenderer(
  message: RenderableMessage,
  options: MessageRenderOptions,
  theme: Theme,
): Component {
  return {
    invalidate(): void {},
    render(width: number): string[] {
      const pad = ' '.repeat(Math.max(0, options.outputPad))
      const usable = Math.max(12, width - pad.length)
      const details = isRecord(message.details) ? message.details : undefined
      const runs = asArray(details?.runs).filter(isRecord)
      const blocks = messageText(message).split(/\n{2,}/)
      const lines: string[] = []

      if (runs.length === 0) {
        lines.push(
          renderRow(usable, [
            { text: `${GLYPH} `, style: (text) => theme.fg('accent', text) },
            {
              text: 'run',
              style: (text) => theme.bold(theme.fg('customMessageLabel', text)),
            },
          ]),
        )
        for (const line of wrapText(messageText(message), usable - 2)) {
          if (line !== '') {
            lines.push(
              renderRow(usable, [
                { text: `  ${line}`, style: (text) => theme.fg('muted', text) },
              ]),
            )
          }
        }
        return lines.map((line) => `${pad}${line}`)
      }

      for (const [index, run] of runs.entries()) {
        const runId = asText(run.runId)
        const status = asText(run.status) || 'unknown'
        const docId = asText(run.docId)
        const color = RUN_STATUS_COLORS[status] ?? 'muted'
        const mark =
          status === 'done'
            ? '✓'
            : status === 'failed'
              ? '✗'
              : status === 'cancelled'
                ? '⊘'
                : '•'
        const title: Segment[] = [
          { text: `${GLYPH} `, style: (text) => theme.fg('accent', text) },
          {
            text: 'run',
            style: (text) => theme.bold(theme.fg('customMessageLabel', text)),
          },
        ]
        if (runId) {
          title.push({
            text: ` ${clip(runId, 18)}`,
            style: (text) => theme.fg('muted', text),
          })
        }
        title.push({
          text: ` · ${status}`,
          style: (text) => theme.fg(color, text),
        })
        if (docId) {
          title.push({
            text: ` · doc ${clip(docId, 12)}`,
            style: (text) => theme.fg('dim', text),
          })
        }
        lines.push(
          renderRow(
            usable,
            joinColumns(
              title,
              [{ text: mark, style: (text) => theme.fg(color, text) }],
              usable,
            ),
          ),
        )

        // The first line of each block is the same generic sentence the header
        // already states; stages/failures/next-step follow it.
        const body = blocks[index]?.split('\n').slice(1) ?? []
        for (const raw of body) {
          const line = raw.trim()
          if (line === '') continue
          const token: ThemeColor = line.startsWith('Failures:')
            ? 'error'
            : line.startsWith('Call ')
              ? 'dim'
              : 'muted'
          for (const wrapped of wrapText(line, usable - 2)) {
            lines.push(
              renderRow(usable, [
                {
                  text: `  ${wrapped}`,
                  style: (text) => theme.fg(token, text),
                },
              ]),
            )
          }
        }
        if (index < runs.length - 1) lines.push('')
      }

      return lines.map((line) => `${pad}${line}`)
    },
  }
}
