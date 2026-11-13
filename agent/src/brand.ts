import { existsSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

import type { Theme, ThemeColor } from '@earendil-works/pi-coding-agent'

import type { SessionMode } from './modes.js'
import {
  clipSegments,
  countLabel,
  joinColumns,
  plainWidth,
  renderRow,
  renderSegments,
  type Segment,
} from './uiText.js'

/**
 * MBForge visual identity for the pi agent CLI.
 *
 * The palette mirrors `frontend/src/styles/theme.css` (precision-instrument
 * indigo, violet, cyan, semantic green/amber/red) and ships as two pi themes in
 * `agent/themes/`. The startup banner is the one framed surface: terminal
 * convention reserves boxes for moments that need a frame (welcome, approval),
 * while the transcript itself stays open. Everything else uses the three-tier
 * text hierarchy the agent CLIs converged on: bold identity, default content,
 * muted/dim metadata.
 */

/** Directory of the shipped themes; resolves next to `dist/extension.js`. */
const THEME_DIR = fileURLToPath(new URL('../themes', import.meta.url))

const GLYPH = '⬡'
const SOLID = '⬢'
const TAGLINE = 'molecular knowledge & AI workbench'
const MAX_BANNER = 78
/** Below this width the frame costs more than it communicates. */
const MIN_BANNER = 46

export interface BrandState {
  mode: SessionMode
  backend: string
  online: boolean
  toolCount: number
  localToolCount: number
  /** Last worker status reported by get_worker_status, when the agent called it. */
  queue?: { status: string; active: number; backlog: number } | undefined
  /** Output tokens per second; `tpsLive` marks the streaming estimate. */
  tps?: number | undefined
  tpsLive?: boolean | undefined
}

/** Theme paths contributed through pi's `resources_discover` event. */
export function brandThemePaths(): string[] {
  return existsSync(THEME_DIR) ? [THEME_DIR] : []
}

function statusFacts(
  theme: Theme,
  state: BrandState,
  width: number,
): Segment[] {
  const modeColor = state.mode === 'auto' ? 'accent' : 'warning'
  const row: Segment[] = [
    { text: '● ', style: (text) => theme.fg(modeColor, text) },
    {
      text: state.mode,
      style: (text) => theme.bold(theme.fg(modeColor, text)),
    },
    { text: '  ·  ', style: (text) => theme.fg('dim', text) },
    {
      text: countLabel(state.toolCount, 'capability', 'capabilities'),
      style: (text) => theme.fg('muted', text),
    },
  ]
  if (state.localToolCount > 0) {
    const repo: Segment[] = [
      { text: '  ·  ', style: (text) => theme.fg('dim', text) },
      {
        text: countLabel(state.localToolCount, 'repo tool', 'repo tools'),
        style: (text) => theme.fg('warning', text),
      },
    ]
    if (plainWidth(row) + plainWidth(repo) <= width) row.push(...repo)
  }
  return row
}

function frame(
  theme: Theme,
  total: number,
  contentWidth: number,
  rows: Segment[][],
): string[] {
  const border = (text: string) => theme.fg('borderMuted', text)
  const rule = (left: string, right: string) =>
    `  ${border(`${left}${'─'.repeat(total - 2)}${right}`)}`
  const body = rows.map((row) => {
    const clipped = clipSegments(row, contentWidth)
    const padding = ' '.repeat(Math.max(0, contentWidth - plainWidth(clipped)))
    return `  ${border('│')} ${renderSegments(clipped)}${padding} ${border('│')}`
  })
  return [rule('╭', '╮'), ...body, rule('╰', '╯'), '']
}

/**
 * Compact startup banner shown above the chat: identity on the left, live
 * backend health on the right, then mode/capability facts and a tagline.
 * Width tiers: framed two-column at >= 48 columns, stacked and unframed below,
 * with the offline remedy added only when something is wrong.
 */
export function brandHeader(theme: Theme, state: BrandState) {
  return {
    invalidate(): void {},
    render(width: number): string[] {
      const safeWidth = Math.max(1, width)
      const brand: Segment[] = [
        {
          text: `${GLYPH}─${GLYPH}`,
          style: (text) => theme.fg('accent', text),
        },
        { text: '  ' },
        {
          text: 'M B F O R G E',
          style: (text) => theme.bold(theme.fg('accent', text)),
        },
      ]
      const health: Segment[] = state.online
        ? [
            { text: '● ', style: (text) => theme.fg('success', text) },
            { text: state.backend, style: (text) => theme.fg('dim', text) },
          ]
        : [{ text: '⚠ offline', style: (text) => theme.fg('warning', text) }]
      const tagline: Segment[] = [
        { text: TAGLINE, style: (text) => theme.fg('muted', text) },
      ]
      const total = Math.min(safeWidth - 2, MAX_BANNER)
      const framed = total >= MIN_BANNER
      const textWidth = framed ? total - 4 : safeWidth
      const hint: Segment[] | undefined = state.online
        ? undefined
        : [
            {
              text:
                textWidth >= 72
                  ? '⚠ backend offline — start it with backend_control or /mbforge reload'
                  : '⚠ backend offline — use backend_control',
              style: (text) => theme.fg('warning', text),
            },
          ]

      if (!framed) {
        const indent = '  '
        return [
          renderRow(safeWidth, [{ text: indent }, ...brand]),
          renderRow(safeWidth, [{ text: indent }, ...tagline]),
          renderRow(safeWidth, [
            { text: indent },
            ...statusFacts(theme, state, safeWidth),
          ]),
          renderRow(safeWidth, [{ text: indent }, ...health]),
          ...(hint ? [renderRow(safeWidth, [{ text: indent }, ...hint])] : []),
          '',
        ]
      }

      const contentWidth = total - 4
      return frame(theme, total, contentWidth, [
        joinColumns(brand, health, contentWidth),
        tagline,
        statusFacts(theme, state, contentWidth),
        ...(hint ? [hint] : []),
      ])
    },
  }
}

/**
 * Molecule-pulse working indicator. Every frame is one cell wide so the
 * spinner never shifts the row it occupies; only the colour and the hex fill
 * change. 100 ms matches the modal tick rate across agent CLIs.
 */
export function brandWorkingFrames(theme: Theme): string[] {
  const frames: ReadonlyArray<readonly [ThemeColor, string]> = [
    ['dim', GLYPH],
    ['muted', GLYPH],
    ['accent', SOLID],
    ['borderAccent', SOLID],
    ['accent', GLYPH],
    ['muted', GLYPH],
  ]
  return frames.map(([token, glyph]) => theme.fg(token, glyph))
}

/** Host:port for display; falls back to the raw URL when unparsable. */
export function backendLabel(url: string): string {
  try {
    return new URL(url).host
  } catch {
    return url
  }
}
