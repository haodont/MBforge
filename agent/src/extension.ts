import type { ExtensionAPI } from '@mariozechner/pi-coding-agent'

import { loadCapabilityTools, type AgentMode, type CapabilityTool } from './capabilities.js'

/**
 * Pi extension entry point.
 *
 * `pi --no-builtin-tools -e ./dist/extension.js` opens pi's normal interactive
 * CLI (including `/login`, `/model`, sessions, themes) with the MBForge
 * capability tools registered. Provider login is intentionally left to pi.
 *
 * If the MBForge backend is not running, registration degrades to zero tools
 * so pi still opens for provider login; `/mbforge` reports the failure.
 */
export default async function mbforgeExtension(pi: ExtensionAPI): Promise<void> {
  const mode: AgentMode =
    process.env.MBFORGE_AGENT_MODE === 'edit' ? 'edit' : 'readonly'

  let tools: CapabilityTool[] = []
  let loadError: string | undefined
  try {
    tools = await loadCapabilityTools(mode)
  } catch (error) {
    loadError = error instanceof Error ? error.message : String(error)
  }

  for (const tool of tools) {
    pi.registerTool(tool)
  }

  pi.on('session_start', async (_event, ctx) => {
    if (loadError) {
      ctx.ui.setStatus('mbforge', 'MBForge backend unavailable')
      ctx.ui.notify(
        `MBForge backend unavailable: ${loadError}. Start the backend and relaunch.`,
        'warning',
      )
      return
    }
    ctx.ui.setStatus('mbforge', `MBForge ${mode} · ${tools.length} tools`)
  })

  pi.registerCommand('mbforge', {
    description: 'Show MBForge capability mode and registered tools',
    handler: async (_args, ctx) => {
      if (loadError) {
        ctx.ui.notify(
          `MBForge backend unavailable: ${loadError}. Start the backend and relaunch.`,
          'warning',
        )
        return
      }
      ctx.ui.notify(
        `MBForge ${mode} mode: ${tools.map((tool) => tool.name).join(', ')}`,
        'info',
      )
    },
  })
}
