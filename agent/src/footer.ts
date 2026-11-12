import type { Component } from '@earendil-works/pi-tui'
import type {
  ContextUsage,
  ExtensionContext,
  ReadonlyFooterDataProvider,
  Theme,
  ThemeColor,
} from '@earendil-works/pi-coding-agent'

import type { BrandState } from './brand.js'
import { joinColumns, plainWidth, renderRow, type Segment } from './uiText.js'

/**
 * The MBForge status line.
 *
 * Replaces pi's built-in footer with the same information the workbench shows
 * in its own chrome: brand, session mode, capability count, backend health,
 * model, working directory, token totals, and context usage. Two dense rows
 * with `·` separators; the right column is reserved for model and usage so a
 * long path clips first. Rows are plain segments styled last, so ANSI escapes
 * never count toward the width.
 */

const GLYPH = '⬡'

/**
 * The footer only reads usage totals, so it narrows the session entry union to
 * the fields it sums instead of importing pi's internal entry types (the
 * package root does not export them).
 */
interface UsageView {
  input?: number | undefined
  output?: number | undefined
  cacheRead?: number | undefined
  cacheWrite?: number | undefined
  cost?: { total?: number | undefined } | undefined
}

interface SessionEntryView {
  type: string
  usage?: UsageView | undefined
  message?:
    | {
        role?: string | undefined
        usage?: UsageView | undefined
        durationMs?: number | undefined
      }
    | undefined
}

interface Totals {
  input: number
  output: number
  cacheRead: number
  cacheWrite: number
  cost: number
}

interface SessionStats {
  key: string
  totals: Totals
  tps?: number | undefined
}

function addUsage(totals: Totals, usage: UsageView): void {
  totals.input += usage.input ?? 0
  totals.output += usage.output ?? 0
  totals.cacheRead += usage.cacheRead ?? 0
  totals.cacheWrite += usage.cacheWrite ?? 0
  totals.cost += usage.cost?.total ?? 0
}

/** Sum usage over the session; cached until an append or model switch. */
function collectStats(entries: readonly SessionEntryView[], key: string): SessionStats {
  const totals: Totals = { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, cost: 0 }
  let tps: number | undefined
  for (const entry of entries) {
    if (entry.type === 'usage' && entry.usage) {
      addUsage(totals, entry.usage)
    } else if (entry.type === 'message' && entry.message) {
      const message = entry.message
      if (message.role === 'assistant' && message.usage) {
        addUsage(totals, message.usage)
        const output = message.usage.output ?? 0
        tps = undefined
        if (typeof message.durationMs === 'number' && message.durationMs > 0 && output > 0) {
          tps = output / (message.durationMs / 1000)
        }
      } else if (message.role === 'toolResult' && message.usage) {
        addUsage(totals, message.usage)
      }
    } else if ((entry.type === 'compaction' || entry.type === 'branch_summary') && entry.usage) {
      addUsage(totals, entry.usage)
    }
  }
  return { key, totals, tps }
}

function formatTokens(count: number): string {
  if (count < 1000) return String(count)
  if (count < 10000) return `${(count / 1000).toFixed(1)}k`
  if (count < 1000000) return `${Math.round(count / 1000)}k`
  if (count < 10000000) return `${(count / 1000000).toFixed(1)}M`
  return `${Math.round(count / 1000000)}M`
}

/** Home-relative path for the footer (`~` on this machine's home directory). */
function displayPath(cwd: string): string {
  const home = process.env.HOME || process.env.USERPROFILE
  if (!home) return cwd
  const normalizedCwd = cwd.replaceAll('\\', '/').replace(/\/+$/, '')
  const normalizedHome = home.replaceAll('\\', '/').replace(/\/+$/, '')
  if (normalizedCwd === normalizedHome) return '~'
  if (normalizedCwd.startsWith(`${normalizedHome}/`)) {
    return `~/${normalizedCwd.slice(normalizedHome.length + 1)}`
  }
  return cwd
}

/** Token totals and context usage as right-aligned footer segments. */
function usageSegments(
  theme: Theme,
  stats: SessionStats,
  usage: ContextUsage | undefined,
  modelWindow: number | undefined,
  compact: boolean,
  tps: { value: number; live: boolean } | undefined,
): Segment[] {
  const parts: Array<{ text: string; color: ThemeColor }> = []
  if (stats.totals.input > 0) {
    parts.push({ text: `↑${formatTokens(stats.totals.input)}`, color: 'muted' })
  }
  if (stats.totals.output > 0) {
    parts.push({ text: `↓${formatTokens(stats.totals.output)}`, color: 'muted' })
  }
  if (tps) {
    parts.push({
      text: `${tps.live ? '~' : ''}${compact ? Math.round(tps.value) : tps.value.toFixed(1)} tps`,
      color: tps.live ? 'accent' : 'muted',
    })
  }
  if (!compact && stats.totals.cacheRead > 0) {
    parts.push({ text: `R${formatTokens(stats.totals.cacheRead)}`, color: 'muted' })
  }
  if (!compact && stats.totals.cost >= 0.0005) {
    parts.push({ text: `$${stats.totals.cost.toFixed(3)}`, color: 'muted' })
  }
  const window = usage?.contextWindow ?? modelWindow
  const percent = usage?.percent
  if (typeof percent === 'number') {
    const color: ThemeColor = percent > 90 ? 'error' : percent > 70 ? 'warning' : 'muted'
    parts.push({
      text: compact ? `${percent.toFixed(0)}%` : `${percent.toFixed(1)}%/${formatTokens(window ?? 0)}`,
      color,
    })
  } else if (!compact && typeof window === 'number' && window > 0) {
    parts.push({ text: `?/${formatTokens(window)}`, color: 'muted' })
  }
  const row: Segment[] = []
  for (const part of parts) {
    if (row.length > 0) row.push({ text: ' · ', style: (text) => theme.fg('dim', text) })
    row.push({ text: part.text, style: (text) => theme.fg(part.color, text) })
  }
  return row
}

/**
 * Build the custom footer. `ctx` is the live extension context: its getters
 * read the active session and model, so a resumed session or `/model` switch is
 * reflected on the next frame. The usage scan is cached by leaf/entry count.
 */
export function brandFooter(
  theme: Theme,
  state: BrandState,
  ctx: ExtensionContext,
  footerData: ReadonlyFooterDataProvider,
): Component {
  let cached: SessionStats | undefined

  return {
    invalidate(): void {},
    render(width: number): string[] {
      const safeWidth = Math.max(1, width)
      try {
        const entries = ctx.sessionManager.getEntries()
        const key = `${ctx.sessionManager.getLeafId() ?? ''}:${entries.length}:${ctx.model?.provider ?? ''}/${ctx.model?.id ?? ''}`
        if (cached?.key !== key) cached = collectStats(entries, key)
        const stats = cached

        const modeColor: ThemeColor = state.mode === 'auto' ? 'accent' : 'warning'
        const base: Segment[] = [
          { text: `${GLYPH} `, style: (text) => theme.fg('accent', text) },
          { text: 'MBForge', style: (text) => theme.bold(theme.fg('text', text)) },
          { text: '  ' },
          { text: state.mode, style: (text) => theme.bold(theme.fg(modeColor, text)) },
          { text: ' · ', style: (text) => theme.fg('dim', text) },
          { text: `${state.toolCount} caps`, style: (text) => theme.fg('muted', text) },
        ]
        if (state.localToolCount > 0) {
          base.push({ text: ' · ', style: (text) => theme.fg('dim', text) })
          base.push({
            text: `${state.localToolCount} repo`,
            style: (text) => theme.fg('warning', text),
          })
        }

        // Health degrades host:port -> "online" -> omitted; the mode and
        // capability count never clip because they identify the session.
        const healthFull: Segment[] = state.online
          ? [
              { text: ' · ', style: (text) => theme.fg('dim', text) },
              { text: '● ', style: (text) => theme.fg('success', text) },
              { text: state.backend, style: (text) => theme.fg('dim', text) },
            ]
          : [
              { text: ' · ', style: (text) => theme.fg('dim', text) },
              { text: '⚠ offline', style: (text) => theme.fg('warning', text) },
            ]
        const healthCompact: Segment[] =
          state.online
            ? [
                { text: ' · ', style: (text) => theme.fg('dim', text) },
                { text: '● online', style: (text) => theme.fg('success', text) },
              ]
            : healthFull
        const brandRow =
          plainWidth([...base, ...healthFull]) <= safeWidth
            ? [...base, ...healthFull]
            : plainWidth([...base, ...healthCompact]) <= safeWidth
              ? [...base, ...healthCompact]
              : base
        const queueRow: Segment[] = state.queue
          ? [
              { text: ' · ', style: (text) => theme.fg('dim', text) },
              {
                text: `queue ${state.queue.active}/${state.queue.backlog}`,
                style: (text) =>
                  theme.fg(
                    state.queue?.status === 'online' && state.queue.backlog === 0
                      ? 'muted'
                      : 'warning',
                    text,
                  ),
              },
            ]
          : []
        const combined = [...brandRow, ...queueRow]
        const brandLineWithQueue = plainWidth(combined) <= safeWidth ? combined : brandRow

        const model = ctx.model
        const modelRow: Segment[] = model
          ? [
              { text: model.id, style: (text) => theme.fg('muted', text) },
              ...(ctx.thinkingLevel
                ? [
                    { text: ' · ', style: (text: string) => theme.fg('dim', text) },
                    { text: ctx.thinkingLevel, style: (text: string) => theme.fg('dim', text) },
                  ]
                : []),
            ]
          : [{ text: 'no model', style: (text) => theme.fg('dim', text) }]
        const brandLine =
          plainWidth(brandLineWithQueue) + 1 + plainWidth(modelRow) <= safeWidth
            ? joinColumns(brandLineWithQueue, modelRow, safeWidth)
            : brandLineWithQueue

        const path: Segment[] = [
          { text: displayPath(ctx.sessionManager.getCwd()), style: (text) => theme.fg('dim', text) },
        ]
        const branch = footerData.getGitBranch()
        if (branch) {
          path.push({ text: ` (${branch})`, style: (text) => theme.fg('muted', text) })
        }
        const sessionName = ctx.sessionManager.getSessionName()
        if (sessionName) {
          path.push({ text: ` • ${sessionName}`, style: (text) => theme.fg('muted', text) })
        }

        const compact = safeWidth < 80
        const tps =
          state.tps !== undefined
            ? { value: state.tps, live: state.tpsLive === true }
            : stats.tps !== undefined
              ? { value: stats.tps, live: false }
              : undefined
        const usage = usageSegments(
          theme,
          stats,
          ctx.getContextUsage(),
          ctx.model?.contextWindow,
          compact,
          tps,
        )
        const lines = [
          renderRow(safeWidth, brandLine),
          renderRow(safeWidth, joinColumns(path, usage, safeWidth)),
        ]

        const statusLine = [...footerData.getExtensionStatuses().entries()]
          .sort(([left], [right]) => left.localeCompare(right))
          .map(([, value]) => value.replace(/[\r\n\t]+/g, ' ').trim())
          .filter((value) => value.length > 0)
          .join(' · ')
        if (statusLine) {
          lines.push(renderRow(safeWidth, [{ text: statusLine, style: (text) => theme.fg('dim', text) }]))
        }
        return lines
      } catch {
        // A footer must never take the session down; a minimal brand row is
        // better than a stack trace in the status area.
        return [
          renderRow(safeWidth, [{ text: `${GLYPH} MBForge`, style: (text) => theme.fg('accent', text) }]),
        ]
      }
    },
  }
}
