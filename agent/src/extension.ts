import type { ExtensionAPI } from '@earendil-works/pi-coding-agent'
import { setTimeout as sleep } from 'node:timers/promises'

import {
  backendLabel,
  brandHeader,
  brandStatus,
  brandThemePaths,
  brandWorkingFrames,
  type BrandState,
} from './brand.js'
import {
  backendBaseUrl,
  loadCapabilityTools,
  type AgentMode,
  type CapabilityTool,
} from './capabilities.js'

// Bound worst-case startup: a few short attempts tolerate a backend that is
// still coming up, then degrade to zero tools so pi opens promptly.
const MANIFEST_ATTEMPTS = 3
const MANIFEST_RETRY_DELAY_MS = 400

async function loadCapabilityToolsWithRetry(
  mode: AgentMode,
): Promise<CapabilityTool[]> {
  let lastError: unknown
  for (let attempt = 1; attempt <= MANIFEST_ATTEMPTS; attempt += 1) {
    try {
      return await loadCapabilityTools(mode)
    } catch (error) {
      lastError = error
      if (attempt < MANIFEST_ATTEMPTS) {
        await sleep(MANIFEST_RETRY_DELAY_MS)
      }
    }
  }
  throw lastError instanceof Error ? lastError : new Error(String(lastError))
}

/**
 * Pi extension entry point.
 *
 * `pi --no-builtin-tools -e ./dist/extension.js` opens pi's normal interactive
 * CLI (including `/login`, `/model`, sessions, themes) with the MBForge
 * capability tools registered. Provider login is intentionally left to pi.
 *
 * The extension also applies the MBForge identity: it contributes the shipped
 * `themes/` directory, replaces the startup header with the workbench banner,
 * and turns the footer status and working indicator into MBForge furniture.
 *
 * If the MBForge backend is not running, registration degrades to zero tools
 * so pi still opens for provider login; the header reports the offline state.
 */
export default async function mbforgeExtension(pi: ExtensionAPI): Promise<void> {
  const mode: AgentMode =
    process.env.MBFORGE_AGENT_MODE === 'edit' ? 'edit' : 'readonly'

  let tools: CapabilityTool[] = []
  let loadError: string | undefined
  try {
    tools = await loadCapabilityToolsWithRetry(mode)
  } catch (error) {
    loadError = error instanceof Error ? error.message : String(error)
  }

  const state: BrandState = {
    mode,
    backend: backendLabel(backendBaseUrl()),
    online: loadError === undefined,
    toolCount: tools.length,
  }

  for (const tool of tools) {
    pi.registerTool(tool)
  }

  // Contribute the palette during resource discovery as well, so direct
  // `pi -e ./dist/extension.js` launches find the themes without the npm
  // script's `--theme` flag.
  pi.on('resources_discover', () => ({ themePaths: brandThemePaths() }))

  pi.on('session_start', async (_event, ctx) => {
    ctx.ui.setHeader((_tui, theme) => brandHeader(theme, state))
    ctx.ui.setStatus('mbforge', brandStatus(state))
    ctx.ui.setWorkingIndicator({
      frames: brandWorkingFrames(ctx.ui.theme),
      intervalMs: 160,
    })
    ctx.ui.setWorkingMessage('MBForge · working')
    if (loadError) {
      ctx.ui.notify(
        `MBForge backend unavailable: ${loadError}. Start the backend and relaunch.`,
        'warning',
      )
    }
  })

  pi.registerCommand('mbforge', {
    description: 'Show MBForge capability mode, backend, and registered tools',
    handler: async (_args, ctx) => {
      if (loadError) {
        ctx.ui.notify(
          `MBForge backend unavailable: ${loadError}. Start the backend and relaunch.`,
          'warning',
        )
        return
      }
      const names = tools.map((tool) => tool.name)
      ctx.ui.notify(
        [
          `⬡ MBForge · ${mode} mode`,
          `backend  ${state.backend}`,
          `tools    ${names.length}`,
          names.join(', '),
        ].join('\n'),
        'info',
      )
    },
  })
}
