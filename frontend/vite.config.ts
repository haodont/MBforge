import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'
import { readFileSync } from 'node:fs'
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

  return {
    plugins: [
    react(),
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
    },
    },
  }
})
