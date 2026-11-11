#!/usr/bin/env node
import { spawn } from 'node:child_process'
import { existsSync, mkdirSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

import {
  backendAddress,
  startBackend,
  stopBackend,
} from './backend.mjs'

// Launch pi with a project-owned config directory. Pointing
// PI_CODING_AGENT_DIR at agent/.pi-agent keeps ~/.pi/agent settings, packages,
// extensions, skills, prompts, themes and system-prompt files out of the
// MBForge CLI; only the repo's APPEND_SYSTEM.md and extension load.
const agentRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const repoRoot = dirname(agentRoot)
const agentHome = join(agentRoot, '.pi-agent')
const sessionDir = join(agentHome, 'sessions')
const piEntry = join(
  agentRoot,
  'node_modules',
  '@earendil-works',
  'pi-coding-agent',
  'dist',
  'bundle',
  'cli.js',
)
const extensionPath = join(agentRoot, 'dist', 'extension.js')
const promptPath = join(agentRoot, 'APPEND_SYSTEM.md')
const skillsDir = join(agentRoot, 'skills')

for (const [label, path] of [
  ['pi CLI', piEntry],
  ['MBForge extension', extensionPath],
  ['system prompt', promptPath],
]) {
  if (!existsSync(path)) {
    console.error(
      `Cannot start the MBForge agent: ${label} is missing at ${path}. ` +
        'Run `npm --prefix agent install` and `npm --prefix agent run build` first.',
    )
    process.exit(1)
  }
}

mkdirSync(sessionDir, { recursive: true })

const passthrough = process.argv.slice(2)
const backendMetadataOnly = passthrough.some((arg) =>
  ['--help', '-h', '--version', '-v', '--list-models', '--export'].includes(arg),
)
const startBackendEnabled = !['0', 'false', 'no'].includes(
  (process.env.MBFORGE_AGENT_START_BACKEND ?? '1').toLowerCase(),
)

let backendAddressInfo
try {
  backendAddressInfo = backendAddress()
} catch (error) {
  console.error(
    `Cannot resolve the MBForge backend address: ${error instanceof Error ? error.message : String(error)}`,
  )
  process.exit(1)
}

let backendChild = null
process.once('exit', () => stopBackend(backendChild))

if (startBackendEnabled && !backendMetadataOnly) {
  try {
    const result = await startBackend({
      agentHome,
      repoRoot,
      address: backendAddressInfo,
      onChild: (spawned) => {
        backendChild = spawned
      },
    })
    if (result.started) {
      console.log(
        `MBForge backend started at http://${result.host}:${result.port} (log: ${result.logPath})`,
      )
    } else if (result.reason && result.reason !== 'backend address is not local') {
      console.warn(
        `MBForge backend not started: ${result.reason}` +
          (result.tail ? `\n${result.tail}` : ''),
      )
    }
  } catch (error) {
    console.warn(
      `MBForge backend auto-start failed: ${error instanceof Error ? error.message : String(error)}`,
    )
  }
}

const backendEnv = process.env.MBFORGE_BACKEND_URL
  ? {}
  : {
      MBFORGE_BACKEND_HOST: backendAddressInfo.host,
      MBFORGE_BACKEND_PORT: String(backendAddressInfo.port),
    }

// Built-ins are always registered so `/mbforge mode dev` can activate them;
// the extension deactivates them unless the session mode is dev.
const args = [
  '--offline',
  '--tools',
  '+grep,+find,+ls',
  '--no-skills',
  ...(existsSync(skillsDir) ? ['--skill', skillsDir] : []),
  '--theme',
  join(agentRoot, 'themes'),
  '--use-theme',
  'mbforge-light/mbforge-dark',
  '--append-system-prompt',
  promptPath,
  '-e',
  extensionPath,
  ...passthrough,
]

const child = spawn(process.execPath, [piEntry, ...args], {
  cwd: agentRoot,
  env: {
    ...process.env,
    ...backendEnv,
    PI_CODING_AGENT_DIR: agentHome,
    PI_CODING_AGENT_SESSION_DIR: sessionDir,
  },
  stdio: 'inherit',
})

child.on('error', (error) => {
  console.error(`Failed to start the MBForge agent: ${error.message}`)
  process.exit(1)
})

child.on('exit', (code) => {
  process.exit(code ?? 1)
})
