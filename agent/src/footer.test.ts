// @tested-functions brandFooter
import assert from 'node:assert/strict'
import test from 'node:test'

import type { ExtensionContext, Theme } from '@earendil-works/pi-coding-agent'

import type { BrandState } from './brand.js'
import { brandFooter } from './footer.js'

const theme = {
  fg: (_token: string, text: string) => text,
  bold: (text: string) => text,
} as unknown as Theme

const state: BrandState = {
  mode: 'auto',
  backend: '127.0.0.1:18792',
  online: true,
  toolCount: 20,
  localToolCount: 0,
}

function context(entries: unknown[]): ExtensionContext {
  return {
    model: { id: 'LongCat-2.5', provider: 'custom', contextWindow: 1_048_576 },
    thinkingLevel: 'off',
    sessionManager: {
      getEntries: () => entries,
      getLeafId: () => 'leaf',
      getCwd: () => 'C:/repo',
      getSessionName: () => undefined,
    },
    getContextUsage: () => ({ tokens: 1_000, contextWindow: 1_048_576, percent: 0.1 }),
  } as unknown as ExtensionContext
}

const footerData = {
  getGitBranch: () => 'main',
  getExtensionStatuses: () => new Map<string, string>(),
  getAvailableProviderCount: () => 1,
  onBranchChange: () => () => {},
}

const assistant = {
  type: 'message',
  message: {
    role: 'assistant',
    usage: { input: 1_000, output: 234, cacheRead: 0, cacheWrite: 0, cost: { total: 0 } },
    durationMs: 10_000,
  },
}

test('the footer shows the final response TPS from usage and duration', () => {
  const line = brandFooter(theme, state, context([assistant]), footerData).render(100)[1]
  assert.match(line, /23\.4 tps/)
})

test('a live estimate is marked and compact mode rounds TPS', () => {
  const live = brandFooter(
    theme,
    { ...state, tps: 18.2, tpsLive: true },
    context([]),
    footerData,
  ).render(100)[1]
  assert.match(live, /~18\.2 tps/)

  const compact = brandFooter(theme, state, context([assistant]), footerData).render(60)[1]
  assert.match(compact, /23 tps/)
})
