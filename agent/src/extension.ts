import type { ExtensionAPI } from '@mariozechner/pi-coding-agent'

import { loadCapabilityTools, type AgentMode } from './capabilities.js'

/**
 * Pi extension entry point.
 *
 * `pi --no-builtin-tools -e ./dist/extension.js` opens pi's normal interactive
 * CLI (including `/login`, `/model`, sessions, themes) with the MBForge
 * capability tools registered. Provider login is intentionally left to pi.
 */
export default async function mbforgeExtension(pi: ExtensionAPI): Promise<void> {
  const mode: AgentMode =
    process.env.MBFORGE_AGENT_MODE === 'edit' ? 'edit' : 'readonly'
  const tools = await loadCapabilityTools(mode)
  for (const tool of tools) {
    pi.registerTool(tool)
  }

  pi.on('session_start', async (_event, ctx) => {
    ctx.ui.setStatus('mbforge', `MBForge ${mode} · ${tools.length} tools`)
  })

  pi.registerCommand('mbforge', {
    description: 'Show MBForge capability mode and registered tools',
    handler: async (_args, ctx) => {
      ctx.ui.notify(
        `MBForge ${mode} mode: ${tools.map((tool) => tool.name).join(', ')}`,
        'info',
      )
    },
  })
}
