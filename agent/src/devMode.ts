import {
  defineTool,
  type ExtensionAPI,
  type ExtensionToolContext,
} from '@earendil-works/pi-coding-agent'
import { Type } from 'typebox'

import type { SessionMode } from './modes.js'
import { askUser } from './ask.js'
import { toolRenderers } from './toolRender.js'

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
      promptGuidelines: [
        'Call `request_dev_mode` when the task needs repository/code tools and they are inactive. This tool is the request: do not answer that the user must request dev mode themselves, and do not print commands for them to run instead.',
        'Never assume approval. Use a repository tool only after `switched=true`, when the result says the session is already in dev mode, or when the user says they switched with `/mbforge mode dev`.',
        'If the user declines or dismisses the dialog, do not immediately ask again; explain which repository action is unavailable and continue with the work that does not need it.',
      ],
      parameters: Type.Object({}),
      ...toolRenderers(DEV_MODE_TOOL_NAME),
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
        const answer = await askUser(ctx, {
          kind: 'confirm',
          title: 'Switch MBForge to dev mode?',
          message:
            'The agent will gain repository tools (read, bash, edit, write, grep, find, ls) that can change files in this project. Approve only if you want the agent to work on code in this session.',
          confirm_label: 'Enable dev mode',
          cancel_label: 'Stay in auto',
        })
        if (!answer.confirmed) {
          return result({
            mode: options.getMode(),
            switched: false,
            message: answer.cancelled
              ? 'The user dismissed the dev-mode request; the session stays in auto mode.'
              : 'The user declined dev mode; the session stays in auto mode.',
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
