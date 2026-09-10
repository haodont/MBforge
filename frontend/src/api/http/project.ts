/**
 * Project→Library compat shim (minimal).
 *
 * After project→library migration, only `getCommonDirs` remains: FolderPicker
 * shortcuts (empty on web). All document content reads go through the formal
 * library artifact routes in `library.ts`; nothing here servces raw library
 * artifact paths anymore.
 *
 * Prefer `library.ts` for all new code.
 */

export function getCommonDirs(): { name: string; path: string }[] {
  // No OS folder enumeration in web mode; FolderPicker falls back to manual entry.
  return []
}
