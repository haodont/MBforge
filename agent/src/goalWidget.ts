import type { Component } from '@earendil-works/pi-tui'
import type { ExtensionContext, Theme } from '@earendil-works/pi-coding-agent'

import { goalStateFromBranch, type GoalDefinition } from './goal.js'
import { joinColumns, renderRow, renderSegments, wrapText, type Segment } from './uiText.js'

/**
 * Pinned active-goal checklist below the editor.
 *
 * A goal is the user's committed scope, so it should stay visible while the
 * transcript scrolls. The card is a compact todo: the title and objective, then
 * checkbox rows for requirements and acceptance, and compact constraint /
 * non-goal rows. It reads the active branch so an `update` or a resumed session
 * shows the latest definition; the extension removes it when the goal ends.
 */
export function goalWidget(
  theme: Theme,
  ctx: ExtensionContext,
  goalId: string,
): Component {
  let cache:
    | { length: number; id: string; goal: GoalDefinition | undefined }
    | undefined

  const textStyle = (text: string) => theme.fg('text', text)
  const mutedStyle = (text: string) => theme.fg('muted', text)
  const dimStyle = (text: string) => theme.fg('dim', text)
  const accentStyle = (text: string) => theme.fg('accent', text)

  function section(
    rows: string[],
    label: string,
    items: string[],
    marker: string,
    style: (text: string) => string,
    width: number,
    max: number,
  ): void {
    if (items.length === 0) return
    rows.push(
      renderSegments([
        { text: `  ${label} · ${items.length}`, style: dimStyle },
      ]),
    )
    for (const item of items.slice(0, max)) {
      const lines = wrapText(item, Math.max(8, width - 4))
      for (const [index, line] of lines.entries()) {
        rows.push(
          renderSegments(
            index === 0
              ? [
                  { text: `  ${marker} `, style: dimStyle },
                  { text: line, style },
                ]
              : [{ text: '    ' }, { text: line, style }],
          ),
        )
      }
    }
    if (items.length > max) {
      rows.push(
        renderSegments([
          { text: `    … ${items.length - max} more`, style: dimStyle },
        ]),
      )
    }
  }

  return {
    invalidate(): void {},
    render(width: number): string[] {
      let branch: readonly unknown[]
      try {
        branch = ctx.sessionManager.getBranch()
      } catch {
        // pi invalidates the ctx on session replacement or reload; a widget
        // must never take the render loop down with it.
        return []
      }
      if (
        cache === undefined ||
        cache.length !== branch.length ||
        cache.id !== goalId
      ) {
        cache = {
          length: branch.length,
          id: goalId,
          goal: goalStateFromBranch(branch, goalId)?.goal,
        }
      }
      const goal = cache.goal
      if (!goal) return []

      const rows: string[] = []
      const title: Segment[] = [
        { text: '⬡ ', style: accentStyle },
        { text: 'GOAL', style: (text) => theme.bold(accentStyle(text)) },
        { text: '  ' },
        { text: `“${goal.title}”`, style: (text) => theme.bold(textStyle(text)) },
      ]
      rows.push(
        renderRow(
          width,
          joinColumns(title, [{ text: goal.id, style: dimStyle }], width),
        ),
      )

      if (goal.objective) {
        for (const line of wrapText(goal.objective, Math.max(8, width - 2))) {
          rows.push(
            renderSegments([{ text: '  ' }, { text: line, style: mutedStyle }]),
          )
        }
      }

      section(rows, 'Requirements', goal.requirements, '☐', textStyle, width, 5)
      section(rows, 'Acceptance', goal.acceptance, '☐', textStyle, width, 5)
      section(rows, 'Constraints', goal.constraints, '·', mutedStyle, width, 3)
      section(rows, 'Not in scope', goal.non_goals, '×', dimStyle, width, 3)
      return rows
    },
  }
}
