// @tested-functions capabilityRenderers
import assert from 'node:assert/strict'
import test from 'node:test'

import type { ToolRenderers } from '@earendil-works/pi-coding-agent'

import { capabilityRenderers } from './toolRender.js'

// The renderers are display-only; a theme that returns text unchanged lets the
// assertions read the produced content without parsing ANSI escapes.
const theme = {
  fg: (_color: string, value: string) => value,
  bold: (value: string) => value,
} as never

const context = { durationMs: 12, expanded: false, keyHint: (_k: string, d: string) => d }
const collapsedOptions = { expanded: false, isPartial: false }
const expandedOptions = { expanded: true, isPartial: false }

function result(data: unknown, extra: Record<string, unknown> = {}) {
  return { content: [{ type: 'text', text: JSON.stringify(data) }], details: { success: true, data, ...extra } }
}

function render(renderers: ToolRenderers, view: 'call' | 'result', ...args: unknown[]): string[] {
  const component =
    view === 'call'
      ? renderers.renderCall!(args[0], theme, context as never)
      : renderers.renderResult!(args[0] as never, args[1] as never, theme, context as never)
  return component.render(80)
}

test('search evidence collapses to a one-line summary and reveals items only when expanded — not raw JSON', () => {
  const data = {
    items: Array.from({ length: 5 }, (_unused, index) => ({
      evidence_id: `ev-${index}`,
      doc_id: 'doc-abc',
      page: index + 1,
      kind: 'text',
      title: 'Patent 42',
      file_name: 'source.pdf',
      snippet: `compound ${index} is disclosed`,
      truncated: false,
    })),
  }
  const renderers = capabilityRenderers('search_evidence')
  const collapsed = render(renderers, 'result', result(data), collapsedOptions).join('\n')

  assert.match(collapsed, /✓ 5 evidence/)
  assert.match(collapsed, /▾/)
  assert.ok(!collapsed.includes('p1 ·'), 'collapsed shows no item preview')
  assert.ok(!collapsed.includes('"evidence_id"'), 'must not dump raw JSON')

  const expandedLines = render(renderers, 'result', result(data), expandedOptions)
  assert.match(expandedLines.join('\n'), /p1 · text · Patent 42 · “compound 0 is disclosed”/)
  assert.equal(expandedLines.length, 1 + 5)
})

test('structure verification shows the mass verdict and the designation of each row', () => {
  const data = {
    summary: {
      structures: 2,
      mass_matches: 1,
      mass_mismatches: 1,
      printed_ms_lines: 3,
      printed_ms_unowned: 1,
    },
    items: [
      {
        page: 62,
        evidence_id: 'ev-1',
        label_keys: ['4'],
        mass_check: 'match',
        smiles: 'Cn1cc2c(N)CC3',
        formula: 'C13H19N5',
      },
      {
        page: 63,
        evidence_id: 'ev-2',
        label_keys: ['9'],
        mass_check: 'mismatch',
        smiles: 'Cl.Cn1cc2c(N)CC3',
        formula: 'C13H20ClN5',
      },
    ],
  }
  const renderers = capabilityRenderers('verify_structures')
  const expanded = render(renderers, 'result', result(data), expandedOptions).join('\n')

  assert.match(expanded, /2 structures/)
  assert.match(expanded, /p62 · match · 4 · /)
  assert.match(expanded, /p63 · mismatch · 9 · /)
})

test('mutating and error results report the failure instead of a success checkmark', () => {
  const failed = {
    content: [{ type: 'text', text: 'capability search_molecules failed (400): bad query' }],
    details: {},
    isError: true,
  }
  const lines = render(capabilityRenderers('search_molecules'), 'result', failed, collapsedOptions)

  assert.match(lines[0] ?? '', /✗/)
  assert.match(lines[0] ?? '', /bad query/)
  assert.ok(!/\u2713/.test(lines.join('\n')))
})

test('the call row humanizes the tool name and summarizes key arguments', () => {
  const lines = render(
    capabilityRenderers('search_molecules'),
    'call',
    { query: 'aspirin', mode: 'similarity', top_k: 8 },
  )
  const body = lines.join('\n')

  assert.match(body, /search molecules/)
  assert.match(body, /“aspirin”/)
  assert.match(body, /similarity/)
  assert.match(body, /top 8/)
})

test('page image results render an image row only when inline images are enabled', () => {
  const png =
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Wl2nWQAAAAASUVORK5CYII='
  const imageResult = {
    content: [
      { type: 'text', text: '{"page":1,"width":1,"height":1}' },
      { type: 'image', data: png, mimeType: 'image/png' },
    ],
    details: {
      data: { doc_id: '31fc28463eaae8e3', page: 1, width: 1, height: 1 },
    },
  }
  const renderers = capabilityRenderers('inspect_visual')

  const shown = renderers
    .renderResult!(imageResult as never, collapsedOptions, theme, {
      ...context,
      showImages: true,
    } as never)
    .render(80)
  assert.match(shown[0] ?? '', /p1 · 1×1/)
  assert.ok(shown.length > 1, 'the image component adds a preview or fallback row')

  const hidden = renderers
    .renderResult!(imageResult as never, collapsedOptions, theme, {
      ...context,
      showImages: false,
    } as never)
    .render(80)
  assert.equal(hidden.length, 1)
})
