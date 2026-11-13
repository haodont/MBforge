// @tested-functions toolRenderers, improvementRenderers
import assert from 'node:assert/strict'
import test from 'node:test'

import type { ToolRenderers } from '@earendil-works/pi-coding-agent'

import { improvementRenderers, toolRenderers } from './toolRender.js'

// The renderers are display-only; a theme that returns text unchanged lets the
// assertions read the produced content without parsing ANSI escapes.
const theme = {
  fg: (_color: string, value: string) => value,
  bold: (value: string) => value,
} as never

const context = {
  durationMs: 12,
  expanded: false,
  keyHint: (_k: string, d: string) => d,
}
const collapsedOptions = { expanded: false, isPartial: false }
const expandedOptions = { expanded: true, isPartial: false }

function result(data: unknown, extra: Record<string, unknown> = {}) {
  return {
    content: [{ type: 'text', text: JSON.stringify(data) }],
    details: { success: true, data, ...extra },
  }
}

function render(
  renderers: ToolRenderers,
  view: 'call' | 'result',
  payload: unknown,
  options: Record<string, unknown> = collapsedOptions,
  ctx: Record<string, unknown> = context,
): string[] {
  const component =
    view === 'call'
      ? renderers.renderCall!(payload, theme, ctx as never)
      : renderers.renderResult!(
          payload as never,
          options as never,
          theme,
          ctx as never,
        )
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
  const renderers = toolRenderers('search_evidence')
  const collapsed = render(
    renderers,
    'result',
    result(data),
    collapsedOptions,
  ).join('\n')

  assert.match(collapsed, /✓ 5 evidence/)
  assert.match(collapsed, /▾/)
  assert.ok(!collapsed.includes('p1 ·'), 'collapsed shows no item preview')
  assert.ok(!collapsed.includes('"evidence_id"'), 'must not dump raw JSON')

  const expandedLines = render(
    renderers,
    'result',
    result(data),
    expandedOptions,
  )
  assert.match(
    expandedLines.join('\n'),
    /p1 · text · Patent 42 · “compound 0 is disclosed”/,
  )
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
  const renderers = toolRenderers('verify_structures')
  const expanded = render(
    renderers,
    'result',
    result(data),
    expandedOptions,
  ).join('\n')

  assert.match(expanded, /2 structures/)
  assert.match(expanded, /p62 · match · 4 · /)
  assert.match(expanded, /p63 · mismatch · 9 · /)
})

test('mutating and error results report the failure instead of a success checkmark', () => {
  const failed = {
    content: [
      {
        type: 'text',
        text: 'capability search_molecules failed (400): bad query',
      },
    ],
    details: {},
    isError: true,
  }
  const lines = render(
    toolRenderers('search_molecules'),
    'result',
    failed,
    collapsedOptions,
  )

  assert.match(lines[0] ?? '', /✗/)
  assert.match(lines[0] ?? '', /bad query/)
  assert.ok(!/\u2713/.test(lines.join('\n')))
})

test('the call row humanizes the tool name and summarizes key arguments', () => {
  const lines = render(toolRenderers('search_molecules'), 'call', {
    query: 'aspirin',
    mode: 'similarity',
    top_k: 8,
  })
  const body = lines.join('\n')

  assert.match(body, /search molecules/)
  assert.match(body, /“aspirin”/)
  assert.match(body, /similarity/)
  assert.match(body, /top 8/)
})

/** Pin the image protocol so a developer running the suite inside Windows
 *  Terminal or Kitty gets the same branch as CI. */
function withImageProtocol(value: string, run: () => void): void {
  const previous = process.env.PI_IMAGE_PROTOCOL
  process.env.PI_IMAGE_PROTOCOL = value
  try {
    run()
  } finally {
    if (previous === undefined) delete process.env.PI_IMAGE_PROTOCOL
    else process.env.PI_IMAGE_PROTOCOL = previous
  }
}

test('page image results render an image row only when inline images are enabled', () => {
  const png =
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGP4z8AAAAMBAQDJ/pLvAAAAAElFTkSuQmCC'
  const imageResult = {
    content: [
      { type: 'text', text: '{"page":1,"width":1,"height":1}' },
      { type: 'image', data: png, mimeType: 'image/png' },
    ],
    details: {
      data: { doc_id: '31fc28463eaae8e3', page: 1, width: 1, height: 1 },
    },
  }
  const renderers = toolRenderers('inspect_visual')

  withImageProtocol('none', () => {
    const shown = renderers.renderResult!(
      imageResult as never,
      collapsedOptions,
      theme,
      {
        ...context,
        showImages: true,
      } as never,
    ).render(80)
    assert.match(shown[0] ?? '', /p1 · 1×1/)
    assert.ok(
      shown.length > 1,
      'the image component adds a preview or fallback row',
    )

    const hidden = renderers.renderResult!(
      imageResult as never,
      collapsedOptions,
      theme,
      {
        ...context,
        showImages: false,
      } as never,
    ).render(80)
    assert.equal(hidden.length, 1)
  })
})

test('a sixel terminal gets the image itself instead of pi placeholder text', () => {
  const png =
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGP4z8AAAAMBAQDJ/pLvAAAAAElFTkSuQmCC'
  const imageResult = {
    content: [
      { type: 'text', text: '{"page":1,"width":1,"height":1}' },
      { type: 'image', data: png, mimeType: 'image/png' },
    ],
    details: {
      data: { doc_id: '31fc28463eaae8e3', page: 1, width: 1, height: 1 },
    },
  }
  withImageProtocol('sixel', () => {
    const lines = toolRenderers('inspect_visual').renderResult!(
      imageResult as never,
      collapsedOptions,
      theme,
      {
        ...context,
        showImages: true,
      } as never,
    ).render(80)
    const drawn = lines.join('\n')
    assert.ok(
      !drawn.includes('[Image:'),
      'no text placeholder when the PNG encodes',
    )
    assert.ok(
      (lines.at(-1) ?? '').includes('\x1bPq'),
      'the row carries the sixel sequence',
    )
  })
})

test('suggest improvement shows decisions and the suggestion log instead of raw JSON', () => {
  const renderers = improvementRenderers()
  const proposalArgs = {
    action: 'propose',
    title: 'Cache layout renders per page',
    area: 'pipeline',
    problem: 'Every import re-runs layout.\nRepeated work slows large patents.',
    change: 'Reuse the cached layout within one import.',
    rationale: 'Faster imports.',
    risk: 'Stale cache after a model update.',
    files: ['src/mbforge/server/ingest.py'],
  }
  const proposeCtx = { ...context, args: proposalArgs }

  const call = render(renderers, 'call', proposalArgs).join('\n')
  assert.match(call, /suggest improvement/)
  assert.match(call, /propose · pipeline · “Cache layout renders per page”/)
  assert.ok(
    !call.includes('re-runs layout'),
    'the call row must not dump the proposal body',
  )

  const decision = (overrides: Record<string, unknown>) => {
    const details = {
      action: 'propose',
      path: 'C:/agent/IMPROVEMENTS.json',
      id: 'imp-12ab34cd',
      approved: true,
      executable: true,
      status: 'approved',
      message: 'Approved. Implement exactly this change.',
      ...overrides,
    }
    return {
      content: [{ type: 'text', text: JSON.stringify(details) }],
      details,
    }
  }

  const approved = render(
    renderers,
    'result',
    decision({}),
    collapsedOptions,
    proposeCtx,
  ).join('\n')
  assert.match(
    approved,
    /✓ approved · imp-12ab34cd · “Cache layout renders per page”/,
  )
  assert.match(approved, /▾/)
  assert.ok(
    !approved.includes('re-runs layout'),
    'collapsed hides the proposal body',
  )
  assert.ok(!approved.includes('"executable"'), 'must not dump raw JSON')

  const expanded = render(
    renderers,
    'result',
    decision({}),
    expandedOptions,
    proposeCtx,
  ).join('\n')
  for (const label of ['问题', '改动', '收益', '风险', '涉及']) {
    assert.ok(expanded.includes(label), `expanded proposal shows ${label}`)
  }
  assert.ok(expanded.includes('src/mbforge/server/ingest.py'))

  const declined = render(
    renderers,
    'result',
    decision({
      approved: false,
      executable: false,
      status: 'rejected',
      message: 'Declined. Do not implement this change.',
    }),
    collapsedOptions,
    proposeCtx,
  ).join('\n')
  assert.match(declined, /× declined · imp-12ab34cd/)
  assert.ok(!declined.includes('✓'))

  const readOnly = render(
    renderers,
    'result',
    decision({ executable: false }),
    collapsedOptions,
    proposeCtx,
  ).join('\n')
  assert.match(readOnly, /✓ approved/)
  assert.match(readOnly, /dev mode required/)

  const log = {
    action: 'list',
    path: 'C:/agent/IMPROVEMENTS.json',
    items: [
      {
        id: 'imp-12ab34cd',
        title: 'Cache layout renders per page',
        area: 'pipeline',
        status: 'approved',
      },
      {
        id: 'imp-9f8e7d6c',
        title: 'Typing for molecule rows',
        area: 'capability',
        status: 'implemented',
      },
      {
        id: 'imp-0a1b2c3d',
        title: 'Speculative refactor',
        area: 'other',
        status: 'rejected',
      },
    ],
  }
  const logResult = {
    content: [{ type: 'text', text: JSON.stringify(log) }],
    details: log,
  }
  const listCollapsed = render(
    renderers,
    'result',
    logResult,
    collapsedOptions,
  ).join('\n')
  assert.match(
    listCollapsed,
    /✓ 3 suggestions · 1 approved · 1 implemented · 1 declined/,
  )
  const listExpanded = render(
    renderers,
    'result',
    logResult,
    expandedOptions,
  ).join('\n')
  assert.match(
    listExpanded,
    /✓ imp-12ab34cd {2}pipeline · Cache layout renders per page · approved/,
  )
  assert.match(
    listExpanded,
    /● imp-9f8e7d6c {2}capability · Typing for molecule rows · implemented/,
  )
  assert.match(
    listExpanded,
    /× imp-0a1b2c3d {2}other · Speculative refactor · declined/,
  )

  const empty = {
    action: 'list',
    path: 'C:/agent/IMPROVEMENTS.json',
    items: [],
  }
  const emptyResult = {
    content: [{ type: 'text', text: JSON.stringify(empty) }],
    details: empty,
  }
  assert.match(
    render(renderers, 'result', emptyResult, collapsedOptions).join('\n'),
    /no suggestions/,
  )

  const completeArgs = {
    action: 'complete',
    id: 'imp-12ab34cd',
    note: 'Verified with the ingest tests.',
  }
  const complete = {
    action: 'complete',
    path: 'C:/agent/IMPROVEMENTS.json',
    id: 'imp-12ab34cd',
    status: 'implemented',
    already_completed: false,
  }
  const completeResult = {
    content: [{ type: 'text', text: JSON.stringify(complete) }],
    details: complete,
  }
  const completeCtx = { ...context, args: completeArgs }
  assert.match(
    render(
      renderers,
      'result',
      completeResult,
      collapsedOptions,
      completeCtx,
    ).join('\n'),
    /✓ implemented · imp-12ab34cd/,
  )
  assert.match(
    render(
      renderers,
      'result',
      completeResult,
      expandedOptions,
      completeCtx,
    ).join('\n'),
    /Verified with the ingest tests\./,
  )
  const again = { ...complete, already_completed: true }
  const againResult = {
    content: [{ type: 'text', text: JSON.stringify(again) }],
    details: again,
  }
  assert.match(
    render(
      renderers,
      'result',
      againResult,
      collapsedOptions,
      completeCtx,
    ).join('\n'),
    /already implemented · imp-12ab34cd/,
  )

  const failed = {
    content: [{ type: 'text', text: 'Improvement not found: imp-ffffffff' }],
    details: {},
    isError: true,
  }
  const errorLine =
    render(renderers, 'result', failed, collapsedOptions)[0] ?? ''
  assert.match(errorLine, /✗/)
  assert.match(errorLine, /Improvement not found/)
})

test('local tools render flat details as branded summaries instead of raw JSON', () => {
  const flat = (details: Record<string, unknown>) => ({
    content: [{ type: 'text', text: JSON.stringify(details) }],
    details,
  })

  const memoryAdd = flat({
    action: 'add',
    path: 'C:/agent/MEMORY.md',
    id: 'u-1234abcd',
    type: 'project',
    entry: 'User prefers concise reports.',
    ephemeral_count: 2,
  })
  const addCollapsed = render(
    toolRenderers('memory'),
    'result',
    memoryAdd,
    collapsedOptions,
  ).join('\n')
  assert.match(
    addCollapsed,
    /✓ add · u-1234abcd · project · “User prefers concise reports\.” · 2 ephemeral/,
  )
  assert.ok(!addCollapsed.includes('"action"'), 'must not dump raw JSON')
  const addCall = render(toolRenderers('memory'), 'call', {
    action: 'add',
    content: 'User prefers concise reports.',
  }).join('\n')
  assert.match(addCall, /memory {2}add · “User prefers concise reports\.”/)

  const memoryList = flat({
    action: 'list',
    path: 'C:/agent/MEMORY.md',
    hot: '## user\n- likes brevity',
    cold: 'cold facts',
    ephemeral_count: 2,
  })
  const listCollapsed = render(
    toolRenderers('memory'),
    'result',
    memoryList,
    collapsedOptions,
  ).join('\n')
  assert.match(
    listCollapsed,
    /✓ list · hot 23 chars · cold 10 chars · 2 ephemeral/,
  )
  const listExpanded = render(
    toolRenderers('memory'),
    'result',
    memoryList,
    expandedOptions,
  ).join('\n')
  assert.ok(listExpanded.includes('[hot]'))
  assert.ok(listExpanded.includes('- likes brevity'))

  const ephemeral = flat({
    action: 'ephemeral',
    path: 'C:/agent/MEMORY.md',
    count: 2,
    entries: [
      {
        id: 'u-1234abcd',
        type: 'project',
        date: '2026-11-11',
        content: 'note one',
      },
      {
        id: 'u-5678efab',
        type: 'feedback',
        date: '2026-11-11',
        content: 'note two',
      },
    ],
  })
  assert.match(
    render(toolRenderers('memory'), 'result', ephemeral, collapsedOptions).join(
      '\n',
    ),
    /✓ 2 entries/,
  )
  assert.match(
    render(toolRenderers('memory'), 'result', ephemeral, expandedOptions).join(
      '\n',
    ),
    /project · u-1234abcd · “note one”/,
  )

  const review = flat({
    summary: 'Extraction went well.\nTwo gaps found.',
    lessons: [
      { type: 'feedback', content: 'Check the queue before retrying.' },
    ],
    improvements: [
      {
        title: 'Type molecule rows',
        area: 'capability',
        problem: 'p',
        change: 'c',
        rationale: 'r',
        risk: '',
        files: [],
      },
    ],
    warnings: ['reviewer output was trimmed'],
    memories: [],
    cwd: 'C:/project',
  })
  const reviewCollapsed = render(
    toolRenderers('review_task'),
    'result',
    review,
    collapsedOptions,
  ).join('\n')
  assert.match(reviewCollapsed, /✓ 1 lesson · 1 suggestion · 1 warning/)
  const reviewExpanded = render(
    toolRenderers('review_task'),
    'result',
    review,
    expandedOptions,
  ).join('\n')
  assert.ok(reviewExpanded.includes('Two gaps found.'))
  assert.ok(
    reviewExpanded.includes('feedback · “Check the queue before retrying\.”'),
  )
  assert.ok(reviewExpanded.includes('Type molecule rows'))
  assert.ok(reviewExpanded.includes('reviewer output was trimmed'))
  assert.ok(
    !reviewExpanded.includes('"reviewer output was trimmed"'),
    'plain string rows are not JSON-quoted',
  )
  const reviewCall = render(toolRenderers('review_task'), 'call', {
    instruction: 'focus on the failed extraction path',
  }).join('\n')
  assert.match(
    reviewCall,
    /review task {2}“focus on the failed extraction path”/,
  )

  const goalBegin = flat({
    action: 'begin',
    goal: {
      id: 'goal-12ab34cd',
      title: 'Ship the review center',
      objective: 'Review items resolve.',
      requirements: ['r1'],
    },
  })
  assert.match(
    render(toolRenderers('goal'), 'result', goalBegin, collapsedOptions).join(
      '\n',
    ),
    /✓ goal begin · goal-12ab3… · “Ship the review center”/,
  )
  const goalComplete = flat({
    action: 'complete',
    goal_id: 'goal-12ab34cd',
    review_queued: true,
  })
  assert.match(
    render(
      toolRenderers('goal'),
      'result',
      goalComplete,
      collapsedOptions,
    ).join('\n'),
    /✓ goal complete · goal-12ab3… · review queued/,
  )

  const devMode = flat({
    mode: 'dev',
    switched: true,
    message:
      'The user approved dev mode. Repository and code tools are now active.',
  })
  assert.match(
    render(
      toolRenderers('request_dev_mode'),
      'result',
      devMode,
      collapsedOptions,
    ).join('\n'),
    /✓ The user approved dev mode\. Repository and code tools are now active\./,
  )
  const declined = flat({
    mode: 'auto',
    switched: false,
    message: 'The user declined dev mode; the session stays in auto mode.',
  })
  assert.match(
    render(
      toolRenderers('request_dev_mode'),
      'result',
      declined,
      collapsedOptions,
    ).join('\n'),
    /The user declined dev mode; the session stays in auto mode\./,
  )
})
