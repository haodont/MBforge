import { defineConfig, loadEnv, type ViteDevServer } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'
import { readFileSync } from 'node:fs'
import { spawn } from 'node:child_process'
import net from 'node:net'
import processShim from './process-shim.json'

// Read version from frontend/package.json and bake it into the build
// via Vite's `define`. Update by bumping `version` in package.json
// (the same value is reported by the FastAPI `/openapi.json` `info.version`).
// Resolved at config load time so the value is statically inlined.
const pkg = JSON.parse(
  readFileSync(path.resolve(__dirname, 'package.json'), 'utf-8'),
)

function readPort(value: string | undefined, fallback: number, name: string): number {
  if (!value) return fallback

  const port = Number(value)
  if (!Number.isInteger(port) || port < 1 || port > 65535) {
    throw new Error(`${name} must be an integer between 1 and 65535; received ${value}`)
  }
  return port
}

/** Probe whether a TCP service is already listening on host:port. */
function isPortListening(host: string, port: number): Promise<boolean> {
  return new Promise((resolve) => {
    const socket = new net.Socket()
    const settle = (value: boolean) => {
      socket.removeAllListeners()
      socket.destroy()
      resolve(value)
    }
    socket.setTimeout(1500)
    socket.once('connect', () => settle(true))
    socket.once('timeout', () => settle(false))
    socket.once('error', () => settle(false))
    socket.connect(port, host)
  })
}

/** Kill a spawn tree portably (taskkill under Windows orphans). */
function killProcessTree(child: ReturnType<typeof spawn>): void {
  try {
    if (process.platform === 'win32') {
      spawn('taskkill', ['/pid', String(child.pid), '/T', '/F'])
    } else {
      child.kill('SIGTERM')
    }
  } catch {
    /* best effort — never let teardown throw */
  }
}

/**
 * Dev convenience: when the frontend is started alone (`npm run dev`), also
 * bring up the LLM agent service so chat works without running `dev:all`.
 * Waits until the agent actually answers before returning, so the first chat
 * request never races a still-building process. `dev:all` manages the agent
 * itself and sets `MBFORGE_AGENT_AUTOSTART=0`.
 */
async function ensureAgentServer(
  server: ViteDevServer,
  host: string,
  port: number,
): Promise<void> {
  if (process.env.MBFORGE_AGENT_AUTOSTART === '0') return
  if (await isPortListening(host, port)) return

  const agentDir = path.resolve(__dirname, '..', 'agent')
  // eslint-disable-next-line no-console
  console.log(`[mbforge] LLM agent not on ${host}:${port}; building & starting it…`)
  const child = spawn(
    `npm --prefix "${agentDir}" run build && npm --prefix "${agentDir}" start`,
    { shell: true, stdio: 'inherit', env: { ...process.env, MBFORGE_AGENT_HOST: host, MBFORGE_AGENT_PORT: String(port) } },
  )
  child.once('error', (error) => {
    // eslint-disable-next-line no-console
    console.error(`[mbforge] Failed to start the LLM agent: ${error.message}`)
  })
  server.httpServer?.once('close', () => killProcessTree(child))

  // A build/start failure makes the combined command exit. Bail out of
  // polling so we report that instead of hanging and then timing out.
  let exited = false
  child.once('close', () => { exited = true })

  const deadline = Date.now() + 120_000
  while (Date.now() < deadline && !exited) {
    if (await isPortListening(host, port)) {
      // eslint-disable-next-line no-console
      console.log(`[mbforge] LLM agent ready on ${host}:${port}.`)
      return
    }
    await new Promise((resolve) => setTimeout(resolve, 500))
  }
  // eslint-disable-next-line no-console
  console.error(
    exited
      ? '[mbforge] LLM agent exited before becoming ready — check the build/start messages above.'
      : '[mbforge] Timed out waiting for the LLM agent to become ready.',
  )
}

export default defineConfig(({ mode }) => {
  const environment = { ...loadEnv(mode, __dirname, ''), ...process.env }
  const backendHost = environment.MBFORGE_BACKEND_HOST ?? '127.0.0.1'
  const backendPort = readPort(
    environment.MBFORGE_BACKEND_PORT,
    18792,
    'MBFORGE_BACKEND_PORT',
  )
  const frontendHost = environment.MBFORGE_FRONTEND_HOST ?? 'localhost'
  const frontendPort = readPort(
    environment.MBFORGE_FRONTEND_PORT,
    5173,
    'MBFORGE_FRONTEND_PORT',
  )
  const agentHost = environment.MBFORGE_AGENT_HOST ?? '127.0.0.1'
  const agentPort = readPort(
    environment.MBFORGE_AGENT_PORT ?? '18800',
    18800,
    'MBFORGE_AGENT_PORT',
  )

  return {
    plugins: [
    react(),
    ...(mode === 'development'
      ? [{
          // Dev convenience: starting the frontend alone also starts the LLM
          // agent service so chat works without running `dev:all`. Gated to
          // the Vite dev server only — never during vitest ('test') or build
          // ('production'), where it would otherwise spawn a network service.
          name: 'mbforge-agent-autostart',
          configureServer(server) {
            // Awaiting here blocks Vite from listening until the agent is
            // reachable, so the first chat request can't get ECONNREFUSED.
            return ensureAgentServer(server, agentHost, agentPort)
          },
        }]
      : []),
    {
      // Some pre-bundled deps (e.g. ketcher-standalone) ship with Node-style
      // `process.env.X` references that survive esbuild's `define` pass.
      // Inject a minimal `process` shim into the HTML so those references
      // resolve at runtime instead of throwing `ReferenceError: process is
      // not defined`.
      name: 'process-shim',
      transformIndexHtml() {
        return {
          tags: [
            {
              tag: 'script',
              injectTo: 'head-prepend',
              children:
                "window.process = window.process || { env: { NODE_ENV: 'development' }, browser: true, version: '', nextTick: function (cb) { Promise.resolve().then(cb); }, platform: 'browser' };",
            },
          ],
        }
      },
    },
    ],
    define: {
    // Vite handles `process.env.NODE_ENV` automatically in dev/build;
    // do not polyfill `process` via define — it breaks pre-bundled
    // deps like ketcher-standalone that bundle Node's `util` polyfill.
    'process.env.NODE_ENV': JSON.stringify(process.env.NODE_ENV ?? 'development'),
    global: 'globalThis',
    __APP_VERSION__: JSON.stringify(pkg.version),
    __BACKEND_HOST__: JSON.stringify(backendHost),
    __BACKEND_PORT__: JSON.stringify(backendPort),
    },
  // Vite's top-level `define` is not applied to pre-bundled deps
  // (e.g. ketcher-standalone bundles Node's `util.debuglog` and
  // `console` polyfills that reference `process.env.NODE_DEBUG` and
  // friends). Pass `process` directly through `optimizeDeps.rolldownOptions`
  // so the substitution lands in `node_modules/.vite/deps/*.js`.
  // NOTE: rolldown (Vite 8) moved `define` into `transform.define`; a
  // top-level `define` in rolldown InputOptions is rejected at startup
  // ("Invalid input options ... Expected never but received 'define'").
    optimizeDeps: {
    rolldownOptions: {
      transform: {
      define: {
        global: 'globalThis',
        'process.env.NODE_ENV': JSON.stringify(process.env.NODE_ENV ?? 'development'),
        'process.env': '{}',
        // Minimal Node ``process`` shim for pre-bundled deps that
        // reference ``process.env`` / ``process.nextTick`` etc. The
        // shim lives in ``process-shim.json`` so it can be edited
        // without unbalancing the surrounding TypeScript.
        process: JSON.stringify(processShim).replace(/"function\(([^)]*)\)\{([^}]*)\}"/g, 'function($1){$2}'),
      },
      },
    },
    },
    resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
    },
    server: {
    host: frontendHost,
    port: frontendPort,
    // The backend and docs use this fixed port. Failing instead of silently
    // switching ports makes an already-running dev server immediately visible.
    strictPort: true,
    proxy: {
      '/api': {
        target: `http://${backendHost}:${backendPort}`,
        changeOrigin: true,
      },
      // Same-origin path to the LLM agent service (port 18800). The
      // frontend's `agent.ts` calls `/agent-api/...` in dev.
      '/agent-api': {
        target: `http://${agentHost}:${agentPort}`,
        changeOrigin: true,
        // /agent-api/v1/chat -> /v1/chat
        rewrite: (path) => path.replace(/^\/agent-api/, ''),
      },
    },
    },
  }
})
