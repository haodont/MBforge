/**
 * Build a direct URL to the FastAPI backend, bypassing the Vite dev proxy.
 *
 * `vite.config.ts` injects `__BACKEND_HOST__` and `__BACKEND_PORT__` via
 * `define` so this module resolves to constants at build time and has no
 * runtime cost. `MBFORGE_BACKEND_HOST` and `MBFORGE_BACKEND_PORT` drive both
 * the proxy and these values; `npm run dev:all` derives them from its
 * `MBFORGE_DEV_*` inputs.
 *
 * Use this ONLY when the Vite proxy doesn't fit:
 *   - SSE streams (`EventSource` cannot be proxied as a stream cleanly)
 *   - `<img>` / `<a download>` blob/file URLs that need to load as fast as
 *     possible without paying the proxy hop
 *   - Background fetches (e.g. error reporting with `keepalive: true`) that
 *     should bypass any dev-server middleware
 *
 * For ordinary REST calls under `/api/v1/*`, prefer `httpFetch('/api/v1/...')`
 * so the proxy can forward them with no extra wiring.
 */
declare const __BACKEND_HOST__: string
declare const __BACKEND_PORT__: number

const HOST: string =
  typeof __BACKEND_HOST__ === 'string' && __BACKEND_HOST__ ? __BACKEND_HOST__ : '127.0.0.1'
const PORT: number =
  typeof __BACKEND_PORT__ === 'number' && Number.isFinite(__BACKEND_PORT__)
    ? __BACKEND_PORT__
    : 18792

/** Backend origin (`http://host:port` with no trailing slash). */
export const BACKEND_ORIGIN: string = `http://${HOST}:${PORT}`

/**
 * Compose a URL targeting the backend.
 * @param path absolute path beginning with `/` (e.g. `/api/v1/...`) OR a
 *             full URL, in which case it is returned unchanged.
 * @param query optional query string (without leading `?`) or key/value pairs.
 */
export function backendUrl(path: string, query?: Record<string, string | number> | string): string {
  const base = /^https?:\/\//i.test(path) ? path : `${BACKEND_ORIGIN}${path.startsWith('/') ? path : `/${path}`}`
  if (!query) return base
  const qs =
    typeof query === 'string'
      ? query.startsWith('?')
        ? query.slice(1)
        : query
      : new URLSearchParams(
          Object.entries(query).reduce<Record<string, string>>((acc, [k, v]) => {
            acc[k] = String(v)
            return acc
          }, {}),
        ).toString()
  return qs ? `${base}?${qs}` : base
}
