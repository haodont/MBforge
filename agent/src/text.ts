/**
 * Shared text and value helpers: one-line clipping for rendered rows, value
 * guards for parsed JSON, field validation, and message extraction for
 * unknown throws.
 */

/** Collapse whitespace and clip to `max` characters with an ellipsis. */
export function clip(value: string, max: number): string {
  const single = value.replace(/\s+/g, ' ').trim()
  return single.length > max ? `${single.slice(0, max - 1)}…` : single
}

/** The one record guard for parsed tool results and persisted values. */
export function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

/** The one array guard for optional JSON collections. */
export function asArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : []
}

/** Display text for a thrown value, preserving `Error` messages. */
export function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error)
}

/**
 * Normalize a user- or model-supplied text field: trim, optionally collapse
 * to one line, and reject empty, oversized or control-character content.
 */
export function cleanText(
  value: string,
  field: string,
  max: number,
  singleLine = false,
): string {
  let text = value.replace(/\r\n?/g, '\n').trim()
  if (singleLine) text = text.replace(/\s+/g, ' ')
  if (!text) throw new Error(`${field} must not be empty`)
  if (text.length > max) {
    throw new Error(`${field} must be at most ${max} characters`)
  }
  if (/[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f]/.test(text)) {
    throw new Error(`${field} contains control characters`)
  }
  return text
}
