import concurrently from 'concurrently'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const frontendRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const repositoryRoot = path.resolve(frontendRoot, '..')

function readPort(name, fallback) {
  const value = process.env[name]
  if (value === undefined || value === '') return fallback

  const port = Number(value)
  if (!Number.isInteger(port) || port < 1 || port > 65535) {
    throw new Error(`${name} must be an integer between 1 and 65535; received ${value}`)
  }
  return port
}

const host = process.env.MBFORGE_DEV_HOST ?? '127.0.0.1'
const backendPort = readPort('MBFORGE_DEV_PORT', 18792)
const frontendPort = readPort('MBFORGE_DEV_FRONTEND_PORT', 5173)

if (backendPort === frontendPort) {
  throw new Error('MBFORGE_DEV_PORT and MBFORGE_DEV_FRONTEND_PORT must differ')
}

const developmentEnv = {
  ...process.env,
  MBFORGE_HOST: host,
  MBFORGE_PORT: String(backendPort),
  MBFORGE_BACKEND_HOST: host,
  MBFORGE_BACKEND_PORT: String(backendPort),
  MBFORGE_FRONTEND_HOST: host,
  MBFORGE_FRONTEND_PORT: String(frontendPort),
}

const { result } = concurrently(
  [
    {
      command: 'uv run python -m mbforge --reload --no-browser --replace-existing',
      cwd: repositoryRoot,
      env: developmentEnv,
      name: 'backend',
      prefixColor: 'blue',
    },
    {
      command: 'vite',
      cwd: frontendRoot,
      env: developmentEnv,
      name: 'frontend',
      prefixColor: 'green',
    },
  ],
  {
    killOthersOn: ['failure'],
    prefix: 'name',
  },
)

try {
  await result
} catch {
  process.exitCode = 1
}
