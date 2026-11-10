import { existsSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

import type { Theme } from '@earendil-works/pi-coding-agent'

/**
 * MBForge visual identity for the pi agent CLI.
 *
 * The palette mirrors `frontend/src/styles/theme.css` (precision-instrument
 * indigo, violet, cyan, semantic green/amber/red) and ships as two pi themes in
 * `agent/themes/`. The header, footer status, and working indicator reuse the
 * same tokens so the CLI looks like the workbench it drives.
 */

/** Directory of the shipped themes; resolves next to `dist/extension.js`. */
const THEME_DIR = fileURLToPath(new URL('../themes', import.meta.url))

const GLYPH = '⬡'
const INDENT = '       '

export interface BrandState {
  mode: 'readonly' | 'edit'
  backend: string
  online: boolean
  toolCount: number
}

type Segment = { text: string; style: (text: string) => string }

/** Theme paths contributed through pi's `resources_discover` event. */
export function brandThemePaths(): string[] {
  return existsSync(THEME_DIR) ? [THEME_DIR] : []
}

/**
 * Join styled segments, cutting at `width` visible columns. Truncation happens
 * on plain text before styling so ANSI escapes never count toward the width.
 */
function renderLine(width: number, segments: Segment[]): string {
  let remaining = width
  let output = ''
  for (const segment of segments) {
    if (remaining <= 0) break
    const text =
      segment.text.length <= remaining
        ? segment.text
        : `${segment.text.slice(0, Math.max(0, remaining - 1))}…`
    output += segment.style(text)
    remaining -= text.length
  }
  return output
}

/** Compact startup banner shown above the chat. */
export function brandHeader(theme: Theme, state: BrandState) {
  return {
    invalidate(): void {},
    render(width: number): string[] {
      const wordmark: Segment[] =
        width >= 24
          ? [
              { text: '  ', style: (text) => text },
              {
                text: `${GLYPH}─${GLYPH}`,
                style: (text) => theme.fg('accent', text),
              },
              { text: '  ', style: (text) => text },
              {
                text: 'M B F O R G E',
                style: (text) => theme.bold(theme.fg('accent', text)),
              },
            ]
          : [
              { text: '  ', style: (text) => text },
              {
                text: `${GLYPH} MBFORGE`,
                style: (text) => theme.bold(theme.fg('accent', text)),
              },
            ]

      const tagline: Segment[] = [
        { text: INDENT, style: (text) => text },
        {
          text: 'molecular knowledge & AI workbench',
          style: (text) => theme.fg('muted', text),
        },
      ]

      const facts: Segment[] = [
        { text: INDENT, style: (text) => text },
        {
          text: state.mode === 'edit' ? '● edit' : '● readonly',
          style: (text) =>
            theme.fg(state.mode === 'edit' ? 'warning' : 'success', text),
        },
        { text: ' · ', style: (text) => text },
        {
          text: `${state.toolCount} capabilities`,
          style: (text) => theme.fg('muted', text),
        },
      ]
      if (width >= 46) {
        facts.push({ text: ' · ', style: (text) => text })
        if (state.online) {
          facts.push({
            text: '●',
            style: (text) => theme.fg('success', text),
          })
          facts.push({
            text: ` ${state.backend}`,
            style: (text) => theme.fg('dim', text),
          })
        } else {
          facts.push({
            text: '⚠ backend offline',
            style: (text) => theme.fg('warning', text),
          })
        }
      }

      const ruleWidth = Math.max(0, Math.min(width - 2, 64))
      return [
        renderLine(width, wordmark),
        renderLine(width, tagline),
        renderLine(width, facts),
        `  ${theme.fg('borderMuted', '─'.repeat(ruleWidth))}`,
        '',
      ]
    },
  }
}

/** Footer status text: mode + capability count, or offline state. */
export function brandStatus(state: BrandState): string {
  if (!state.online) return `${GLYPH} MBForge · offline`
  return `${GLYPH} MBForge · ${state.mode} · ${state.toolCount} tools`
}

/** Molecule-pulse working indicator frames, colored from the active theme. */
export function brandWorkingFrames(theme: Theme): string[] {
  return [
    theme.fg('dim', GLYPH),
    theme.fg('muted', GLYPH),
    theme.fg('accent', '⬢'),
    theme.fg('borderAccent', GLYPH),
  ]
}

/** Host:port for display; falls back to the raw URL when unparsable. */
export function backendLabel(url: string): string {
  try {
    return new URL(url).host
  } catch {
    return url
  }
}
