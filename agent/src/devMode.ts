import {
  defineTool,
  type ExtensionAPI,
  type ExtensionToolContext,
} from '@earendil-works/pi-coding-agent'
import { Type } from 'typebox'

import type { SessionMode } from './modes.js'

export const DEV_MODE_TOOL_NAME = 'request_dev_mode'
export const DEV_MODE_TOOL_NAMES = [DEV_MODE_TOOL_NAME] as const

export interface DevModeToolOptions {
  getMode: () => SessionMode
  /** Switch the session and apply the new tool loadout. */
  enableDevMode: (ctx: ExtensionToolContext) => void
}

interface DevModeResult {
  mode: SessionMode
  switched: boolean
  message: string
}

function result(details: DevModeResult): {
  content: { type: 'text'; text: string }[]
  details: DevModeResult
} {
  return {
    content: [{ type: 'text', text: JSON.stringify(details) }],
    details,
  }
}

/**
 * Model-callable request to enter dev mode.
 *
 * Dev mode adds the built-in repository/code tools (read, bash, edit, write,
 * grep, find, ls) to the session, so the model may ask but never switches by
 * itself: the tool opens a confirmation dialog and only an explicit approval
 * changes the mode. Without a dialog-capable UI (print mode), it returns the
 * manual command instead.
 */
export function registerDevModeTool(
  pi: ExtensionAPI,
  options: DevModeToolOptions,
): void {
  pi.registerTool(
    defineTool({
      name: DEV_MODE_TOOL_NAME,
      label: 'Request dev mode',
      description:
        'Ask the user to switch this MBForge session from auto to dev mode, which adds the repository/code tools (read, bash, edit, write, grep, find, ls). Call this when the task needs to inspect or change repository files; the user must approve in the dialog, and a declined request leaves the session unchanged. Never assume the switch happened — check the result.',
      parameters: Type.Object({}),
      async execute(_toolCallId, _params, _signal, _onUpdate, ctx) {
        if (options.getMode() === 'dev') {
          return result({
            mode: 'dev',
            switched: false,
            message:
              'This session is already in dev mode; repository tools are active.',
          })
        }
        if (!ctx.hasUI) {
          return result({
            mode: options.getMode(),
            switched: false,
            message:
              'Dev mode needs the user’s approval, but no confirmation dialog is available in this mode. Ask the user to run /mbforge mode dev.',
          })
        }
        const approved = await ctx.ui.confirm(
          'Switch MBForge to dev mode?',
          'The agent will gain repository tools (read, bash, edit, write, grep, find, ls) that can change files in this project. Approve only if you want the agent to work on code in this session.',
        )
        if (!approved) {
          return result({
            mode: options.getMode(),
            switched: false,
            message:
              'The user declined dev mode; the session stays in auto mode.',
          })
        }
        options.enableDevMode(ctx)
        return result({
          mode: 'dev',
          switched: true,
          message:
            'The user approved dev mode. Repository and code tools are now active.',
        })
      },
    }),
  )
}
