import { spawnSync } from 'node:child_process'
import { mkdirSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

// pi downloads fd/rg lazily unless it runs offline. The MBForge launcher always
// runs offline, so this script fetches them once into the same managed
// directory pi reads from: agent/.pi-agent/bin. It is idempotent and never
// touches ~/.pi/agent or a system installation.
const agentRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const agentHome = join(agentRoot, '.pi-agent')
const binDir = join(agentHome, 'bin')

mkdirSync(binDir, { recursive: true })

process.env.PI_CODING_AGENT_DIR = agentHome
delete process.env.PI_OFFLINE

// Private module path: the package is pinned by agent/package.json, and this
// reuses pi's own release lookup, asset naming, extraction and platform checks.
const toolsManager = join(
  agentRoot,
  'node_modules',
  '@earendil-works',
  'pi-coding-agent',
  'dist',
  'utils',
  'tools-manager.js',
)
const { ensureTool } = await import(pathToFileURL(toolsManager).href)

let failed = false
for (const tool of ['fd', 'rg']) {
  const path = await ensureTool(tool, (status) => {
    console.log(`${tool}: ${status.message}`)
  })
  if (!path) {
    console.error(`${tool}: unavailable`)
    failed = true
    continue
  }
  const version = spawnSync(path, ['--version'], { encoding: 'utf8' })
  if (version.status !== 0) {
    console.error(`${tool}: failed to run ${path}`)
    failed = true
    continue
  }
  console.log(`${tool}: ${version.stdout.trim().split(/\r?\n/)[0]}`)
}

if (failed) {
  process.exitCode = 1
}
