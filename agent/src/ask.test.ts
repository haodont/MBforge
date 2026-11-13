// @tested-functions askUser, registerAskTool
import assert from 'node:assert/strict'
import test from 'node:test'

import type {
  ExtensionAPI,
  ExtensionToolContext,
  ToolDefinition,
} from '@earendil-works/pi-coding-agent'

import { ASK_TOOL_NAME, askUser, registerAskTool } from './ask.js'

interface Harness {
  ctx: ExtensionToolContext
  calls: string[]
  approve: boolean
  selected: string | undefined
  input: string | undefined
}

function harness(): Harness {
  const h: Harness = {
    ctx: undefined as unknown as ExtensionToolContext,
    calls: [],
    approve: true,
    selected: 'Beta',
    input: '  answer  ',
  }
  const ui = {
    confirm: async (title: string) => {
      h.calls.push(`confirm:${title}`)
      return h.approve
    },
    select: async (_title: string, options: string[]) => {
      h.calls.push(`select:${options.join(',')}`)
      return h.selected
    },
    input: async (title: string) => {
      h.calls.push(`input:${title}`)
      return h.input
    },
  }
  h.ctx = {
    mode: 'rpc',
    hasUI: true,
    ui,
  } as unknown as ExtensionToolContext
  return h
}

test('confirm answers map to yes/no and keep the chosen label', async () => {
  const h = harness()
  const yes = await askUser(h.ctx, {
    kind: 'confirm',
    title: 'Apply?',
    confirm_label: 'Apply',
    cancel_label: 'Decline',
  })
  assert.equal(yes.confirmed, true)
  assert.equal(yes.answer, 'yes')
  assert.equal(yes.answer_label, 'Apply')
  assert.equal(yes.cancelled, false)
  assert.deepEqual(h.calls, ['confirm:Apply?'])

  h.approve = false
  const no = await askUser(h.ctx, {
    kind: 'confirm',
    title: 'Apply?',
    confirm_label: 'Apply',
    cancel_label: 'Decline',
  })
  assert.equal(no.confirmed, false)
  assert.equal(no.answer, 'no')
  assert.equal(no.answer_label, 'Decline')
})

test('select answers return the value and its label; cancel is explicit', async () => {
  const h = harness()
  const answer = await askUser(h.ctx, {
    kind: 'select',
    title: 'Which document?',
    options: [
      { value: 'a', label: 'Alpha' },
      { value: 'b', label: 'Beta' },
    ],
  })
  assert.equal(answer.answer, 'b')
  assert.equal(answer.answer_label, 'Beta')
  assert.equal(answer.cancelled, false)
  assert.ok(h.calls.some((call) => call.startsWith('select:Alpha,Beta')))

  h.selected = undefined
  const cancelled = await askUser(h.ctx, {
    kind: 'select',
    title: 'Which document?',
    options: [{ value: 'a', label: 'Alpha' }],
  })
  assert.equal(cancelled.cancelled, true)
  assert.equal(cancelled.answer, null)
})

test('text answers are trimmed; multi-select needs the custom TUI', async () => {
  const text = await askUser(harness().ctx, {
    kind: 'text',
    title: 'Which file?',
    placeholder: 'src/…',
  })
  assert.equal(text.answer, 'answer')
  assert.equal(text.answer_label, 'answer')

  await assert.rejects(
    askUser(harness().ctx, {
      kind: 'multi_select',
      title: 'Which pages?',
      options: [{ value: '1', label: 'Page 1' }],
    }),
    /interactive TUI/,
  )
})

test('the ask tool validates options and returns the answer as details', async () => {
  let registered: ToolDefinition | undefined
  const pi = {
    registerTool: (tool: ToolDefinition) => {
      registered = tool
    },
  } as unknown as ExtensionAPI
  registerAskTool(pi)
  assert.ok(registered)
  assert.equal(registered.name, ASK_TOOL_NAME)

  const h = harness()
  const result = await registered.execute(
    'call-1',
    {
      kind: 'confirm',
      title: 'Proceed?',
      confirm_label: 'Go',
      cancel_label: 'Stop',
    },
    undefined,
    undefined,
    h.ctx,
  )
  const first = result.content[0]
  if (first.type !== 'text') throw new Error('expected a text result')
  const details = JSON.parse(first.text) as Record<string, unknown>
  assert.equal(details.answer, 'yes')
  assert.equal(details.answer_label, 'Go')
  assert.equal(details.cancelled, false)

  await assert.rejects(
    registered.execute(
      'call-2',
      { kind: 'select', title: 'Pick one' },
      undefined,
      undefined,
      h.ctx,
    ),
    /at least one option/,
  )
})
