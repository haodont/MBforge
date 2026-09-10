/**
 * 清理 Windows 路径中的 extended-length path prefix（`\\?\`）以及
 * 旧代码残留的损坏前缀（`?/`）。
 *
 * 同时把反斜杠统一为斜杠，方便前端路径拼接。
 */
export function cleanWindowsPath(p: string): string {
  if (!p) return p
  return p
    .replace(/^\\\\\?\\/, '')      // \\?\C:\...  → C:\...
    .replace(/^\?\//, '')             // ?/C:/...    → C:/...
    .replace(/\\/g, '/')              // \ → /
}
