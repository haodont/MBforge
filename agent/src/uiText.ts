/**
 * Small text-composition helpers for the CLI chrome.
 *
 * Every row is built as plain segments first and styled last, so truncation and
 * right-alignment use visible column counts and an ANSI escape never counts as
 * a column. The helpers are deliberately tiny: the banner, footer, and message
 * card are the only consumers, and each composes its own rows from them.
 */

export interface Segment {
  text: string
  style?: ((value: string) => string) | undefined
}

/** One pluralized count label shared by the banner, footer, and message card. */
export function countLabel(
  count: number,
  singular: string,
  plural: string,
): string {
  return `${count} ${count === 1 ? singular : plural}`
}

/** Word-wrap plain text to `width` columns; long unbroken tokens are clipped. */
export function wrapText(text: string, width: number): string[] {
  const limit = Math.max(1, Math.floor(width))
  const lines: string[] = []
  for (const paragraph of text.split('\n')) {
    const words = paragraph
      .trim()
      .split(/\s+/)
      .filter((word) => word.length > 0)
    if (words.length === 0) {
      lines.push('')
      continue
    }
    let current = ''
    for (const word of words) {
      const piece =
        word.length > limit ? `${word.slice(0, Math.max(0, limit - 1))}…` : word
      if (current === '') current = piece
      else if (current.length + 1 + piece.length <= limit)
        current += ` ${piece}`
      else {
        lines.push(current)
        current = piece
      }
    }
    if (current) lines.push(current)
  }
  return lines
}

/** Visible width of a row before styling. */
export function plainWidth(segments: Segment[]): number {
  let width = 0
  for (const segment of segments) width += segment.text.length
  return width
}

/** Cut a row to `max` columns, ending the last visible segment with `…`. */
export function clipSegments(segments: Segment[], max: number): Segment[] {
  if (max <= 0) return []
  if (plainWidth(segments) <= max) return segments
  const clipped: Segment[] = []
  let remaining = max
  for (const segment of segments) {
    if (remaining <= 0) break
    if (segment.text.length <= remaining) {
      clipped.push(segment)
      remaining -= segment.text.length
      continue
    }
    const keep = Math.max(0, remaining - 1)
    clipped.push({ ...segment, text: `${segment.text.slice(0, keep)}…` })
    break
  }
  return clipped
}

/** Style and join a row. */
export function renderSegments(segments: Segment[]): string {
  let output = ''
  for (const segment of segments) {
    output += segment.style ? segment.style(segment.text) : segment.text
  }
  return output
}

/** One row clipped to `width` visible columns. */
export function renderRow(width: number, segments: Segment[]): string {
  return renderSegments(clipSegments(segments, Math.max(0, width)))
}

/**
 * Push `right` to the edge of a `width`-column row, preserving it when space is
 * tight by clipping `left` first. A row that cannot hold `right` at all drops
 * it rather than truncating the status text into noise.
 */
export function joinColumns(
  left: Segment[],
  right: Segment[],
  width: number,
): Segment[] {
  const rightWidth = plainWidth(right)
  if (rightWidth === 0) return clipSegments(left, width)
  if (rightWidth >= width) return clipSegments(right, width)
  const budget = width - rightWidth - 1
  const fitted = clipSegments(left, Math.max(0, budget))
  const gap = Math.max(1, width - plainWidth(fitted) - rightWidth)
  return [...fitted, { text: ' '.repeat(gap) }, ...right]
}
