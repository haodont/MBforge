// @tested-functions goalWidget
import assert from 'node:assert/strict'
import test from 'node:test'

import type { ExtensionContext, Theme } from '@earendil-works/pi-coding-agent'

import { GOAL_ENTRY_TYPE } from './goal.js'
import { goalWidget } from './goalWidget.js'

const theme = {
  fg: (_token: string, text: string) => text,
  bold: (text: string) => text,
} as unknown as Theme

const goal = {
  id: 'goal-1234abcd',
  title: 'Fix review cache',
  objective: 'Make review counts refresh after a decision.',
  requirements: ['Refresh after decide', 'Keep API stable'],
  acceptance: ['npm test passes'],
  constraints: [],
  non_goals: [],
  created_at: '2026-01-01T00:00:00.000Z',
}

function context(branch: unknown[]): ExtensionContext {
  return {
    sessionManager: { getBranch: () => branch },
  } as unknown as ExtensionContext
}

test('the active goal is pinned with its title and counts', () => {
  const branch: unknown[] = [
    {
      type: 'custom',
      customType: GOAL_ENTRY_TYPE,
      data: { action: 'begin', goal_id: goal.id, goal, at: goal.created_at },
    },
  ]
  const widget = goalWidget(theme, context(branch), goal.id)
  const first = widget.render(100).join('\n')
  assert.match(first, /⬡ GOAL/)
  assert.match(first, /“Fix review cache”/)
  assert.match(first, /Requirements · 2/)
  assert.match(first, /☐ Refresh after decide/)
  assert.match(first, /Acceptance · 1/)
  assert.match(first, /☐ npm test passes/)
  assert.match(first, /goal-1234abcd/)

  branch.push({
    type: 'custom',
    customType: GOAL_ENTRY_TYPE,
    data: {
      action: 'update',
      goal_id: goal.id,
      goal: { ...goal, title: 'Fix review cache v2' },
      at: '2026-01-01T00:01:00.000Z',
    },
  })
  assert.match(widget.render(100).join('\n'), /Fix review cache v2/)
})

test('a widget without an active goal renders nothing', () => {
  const widget = goalWidget(theme, context([]), 'goal-missing')
  assert.deepEqual(widget.render(100), [])
})

test('a replaced session renders nothing instead of throwing', () => {
  const stale = {
    sessionManager: {
      getBranch: () => {
        throw new Error('This extension ctx is stale after session replacement or reload.')
      },
    },
  } as unknown as ExtensionContext
  assert.deepEqual(goalWidget(theme, stale, goal.id).render(100), [])
})
