// @tested-functions registerDevModeTool
import assert from 'node:assert/strict'
import test from 'node:test'

import type {
  ExtensionAPI,
  ExtensionToolContext,
  ToolDefinition,
} from '@earendil-works/pi-coding-agent'

import { DEV_MODE_TOOL_NAME, registerDevModeTool } from './devMode.js'

interface Harness {
  tool: ToolDefinition
  confirmations: number
  enabled: number
}

function harness(mode: 'auto' | 'dev'): Harness {
  let registered: ToolDefinition | undefined
  const h = {
    tool: undefined as unknown as ToolDefinition,
    confirmations: 0,
    enabled: 0,
  }
  const pi = {
    registerTool: (tool: ToolDefinition) => {
      registered = tool
    },
  } as unknown as ExtensionAPI
  registerDevModeTool(pi, {
    getMode: () => mode,
    enableDevMode: () => {
      h.enabled += 1
    },
  })
  assert.ok(registered, 'the tool must be registered')
  h.tool = registered
  return h
}

async function run(
  h: Harness,
  options: { hasUI: boolean; approved: boolean },
): Promise<Record<string, unknown>> {
  const ctx = {
    hasUI: options.hasUI,
    ui: {
      confirm: async () => {
        h.confirmations += 1
        return options.approved
      },
      notify: () => {},
    },
  } as unknown as ExtensionToolContext
  const result = await h.tool.execute('call-1', {}, undefined, undefined, ctx)
  const first = result.content[0]
  if (first.type !== 'text') throw new Error('expected a text tool result')
  return JSON.parse(first.text) as Record<string, unknown>
}

test('dev mode is only entered after the user approves the request', async () => {
  const approved = harness('auto')
  const accepted = await run(approved, { hasUI: true, approved: true })
  assert.equal(approved.tool.name, DEV_MODE_TOOL_NAME)
  assert.equal(approved.confirmations, 1)
  assert.equal(approved.enabled, 1)
  assert.equal(accepted.switched, true)
  assert.equal(accepted.mode, 'dev')

  const declined = harness('auto')
  const refused = await run(declined, { hasUI: true, approved: false })
  assert.equal(declined.confirmations, 1)
  assert.equal(declined.enabled, 0)
  assert.equal(refused.switched, false)
  assert.equal(refused.mode, 'auto')

  const dev = harness('dev')
  const already = await run(dev, { hasUI: true, approved: true })
  assert.equal(dev.confirmations, 0, 'no dialog is needed when already in dev')
  assert.equal(dev.enabled, 0)
  assert.equal(already.switched, false)
  assert.equal(already.mode, 'dev')
})

test('without a dialog the model gets the manual command instead of a switch', async () => {
  const headless = harness('auto')
  const refused = await run(headless, { hasUI: false, approved: true })

  assert.equal(headless.confirmations, 0)
  assert.equal(headless.enabled, 0)
  assert.equal(refused.switched, false)
  assert.match(String(refused.message), /\/mbforge mode dev/)
})
