/**
 * Inline image rendering for the MBForge CLI on terminals pi cannot draw.
 *
 * pi's bundled `Image` component speaks only Kitty and iTerm2, so on Windows
 * Terminal (which pi classifies as `images: null`) a capability image degrades
 * to `[Image: …]`. Windows Terminal 1.22+ implements Sixel, so this module
 * encodes the PNG itself and hands pi a line it will render verbatim.
 *
 * Two constraints shape the output, both read off pi-tui 1.5:
 * - `visibleWidth` recognises CSI/OSC/APC but not DCS, so a bare sixel line
 *   measures wider than the terminal and `tui-alt-screen` slices it to the
 *   line width. Every image line therefore starts with a no-op Kitty APC
 *   (`\x1b_Gq=2\x1b\\`), which `isImageLine` matches; image lines are exempt
 *   from slicing, search highlight and selection repaint.
 * - A sixel image advances the cursor by its own height while pi counts rows
 *   from the component's lines. The block therefore writes `rows - 1` blank
 *   lines, moves the cursor back up, and draws the image over them, so the
 *   reported row count is the space the image occupies.
 */

import { createHash } from 'node:crypto'
import { inflateSync } from 'node:zlib'

/** Keeps a sixel line out of pi's width slicing; see the module comment. */
export const IMAGE_LINE_MARKER = '\x1b_Gq=2\x1b\\'

const DEFAULT_CELL_WIDTH_PX = 9
const DEFAULT_CELL_HEIGHT_PX = 18
const DEFAULT_MAX_WIDTH_CELLS = 72
const DEFAULT_MAX_HEIGHT_CELLS = 24
const MAX_CACHE_ENTRIES = 8

export interface RgbImage {
  width: number
  height: number
  /** Row-major RGB triples, 3 bytes per pixel. */
  pixels: Uint8Array
}

export interface SixelLines {
  lines: string[]
  columns: number
  rows: number
}

export interface SixelOptions {
  maxWidthCells?: number
  maxHeightCells?: number
  cellWidthPx?: number
  cellHeightPx?: number
}

type Env = Record<string, string | undefined>

/** Whether the terminal pi reports as image-less actually renders sixel. */
export function sixelSupported(env: Env = process.env): boolean {
  const forced = (env.PI_IMAGE_PROTOCOL ?? '').trim().toLowerCase()
  if (forced === 'sixel') return true
  if (
    forced === 'kitty' ||
    forced === 'iterm2' ||
    forced === 'none' ||
    forced === '0' ||
    forced === 'off'
  ) {
    return false
  }
  const term = (env.TERM ?? '').toLowerCase()
  if (term.includes('sixel')) return true
  if (!env.WT_SESSION) return false
  const program = (env.TERM_PROGRAM ?? '').toLowerCase()
  if (program && program !== 'windows_terminal') return false
  const match = /^(\d+)\.(\d+)/.exec((env.TERM_PROGRAM_VERSION ?? '').trim())
  if (!match) return false
  const major = Number.parseInt(match[1] ?? '', 10)
  const minor = Number.parseInt(match[2] ?? '', 10)
  return major > 1 || (major === 1 && minor >= 22)
}

/** Decode a base64 PNG into RGB pixels, compositing any alpha over white. */
export function decodePng(bytes: Uint8Array): RgbImage {
  const signature = [137, 80, 78, 71, 13, 10, 26, 10]
  if (
    bytes.length < 8 ||
    signature.some((value, index) => bytes[index] !== value)
  ) {
    throw new Error('not a PNG')
  }
  let width = 0
  let height = 0
  let bitDepth = 0
  let colorType = 0
  let interlace = 0
  const chunks: Uint8Array[] = []
  let palette: Uint8Array | null = null
  for (let offset = 8; offset + 8 <= bytes.length;) {
    const length = readUint32(bytes, offset)
    const type = String.fromCharCode(...bytes.subarray(offset + 4, offset + 8))
    const start = offset + 8
    if (type === 'IHDR') {
      width = readUint32(bytes, start)
      height = readUint32(bytes, start + 4)
      bitDepth = bytes[start + 8] ?? 0
      colorType = bytes[start + 9] ?? 0
      interlace = bytes[start + 12] ?? 0
    } else if (type === 'PLTE') {
      palette = bytes.subarray(start, start + length)
    } else if (type === 'IDAT') {
      chunks.push(bytes.subarray(start, start + length))
    } else if (type === 'IEND') {
      break
    }
    offset = start + length + 4
  }
  if (width <= 0 || height <= 0) throw new Error('PNG has no header')
  if (bitDepth !== 8 || interlace !== 0)
    throw new Error('unsupported PNG layout')
  const channels =
    colorType === 2
      ? 3
      : colorType === 6
        ? 4
        : colorType === 4
          ? 2
          : colorType === 0
            ? 1
            : colorType === 3
              ? 1
              : 0
  if (channels === 0) throw new Error('unsupported PNG colour type')

  const raw = inflateSync(Buffer.concat(chunks))
  const stride = width * channels
  const previous = new Uint8Array(stride)
  const current = new Uint8Array(stride)
  const pixels = new Uint8Array(width * height * 3)
  let source = 0
  for (let row = 0; row < height; row++) {
    const filter = raw[source++] ?? 0
    for (let index = 0; index < stride; index++)
      current[index] = raw[source + index] ?? 0
    source += stride
    unfilterRow(filter, current, previous, channels)
    for (let column = 0; column < width; column++) {
      const at = column * channels
      let red: number
      let green: number
      let blue: number
      let alpha = 255
      if (colorType === 0 || colorType === 4) {
        red = green = blue = current[at] ?? 0
        if (colorType === 4) alpha = current[at + 1] ?? 255
      } else if (colorType === 3) {
        const entry = (current[at] ?? 0) * 3
        red = palette?.[entry] ?? 0
        green = palette?.[entry + 1] ?? 0
        blue = palette?.[entry + 2] ?? 0
      } else {
        red = current[at] ?? 0
        green = current[at + 1] ?? 0
        blue = current[at + 2] ?? 0
        if (colorType === 6) alpha = current[at + 3] ?? 255
      }
      const out = (row * width + column) * 3
      if (alpha === 255) {
        pixels[out] = red
        pixels[out + 1] = green
        pixels[out + 2] = blue
      } else {
        const keep = alpha / 255
        const matte = 255 * (1 - keep)
        pixels[out] = Math.round(red * keep + matte)
        pixels[out + 1] = Math.round(green * keep + matte)
        pixels[out + 2] = Math.round(blue * keep + matte)
      }
    }
    previous.set(current)
  }
  return { width, height, pixels }
}

/** Fit the image into a pixel box with a box filter, never enlarging it. */
export function downscale(
  image: RgbImage,
  maxWidth: number,
  maxHeight: number,
): RgbImage {
  const scale = Math.min(1, maxWidth / image.width, maxHeight / image.height)
  if (scale >= 1) return image
  const width = Math.max(1, Math.floor(image.width * scale))
  const height = Math.max(1, Math.floor(image.height * scale))
  const pixels = new Uint8Array(width * height * 3)
  for (let y = 0; y < height; y++) {
    const top = Math.floor((y * image.height) / height)
    const bottom = Math.max(
      top + 1,
      Math.floor(((y + 1) * image.height) / height),
    )
    for (let x = 0; x < width; x++) {
      const left = Math.floor((x * image.width) / width)
      const right = Math.max(
        left + 1,
        Math.floor(((x + 1) * image.width) / width),
      )
      let red = 0
      let green = 0
      let blue = 0
      let count = 0
      for (let sy = top; sy < bottom; sy++) {
        for (let sx = left; sx < right; sx++) {
          const at = (sy * image.width + sx) * 3
          red += image.pixels[at] ?? 0
          green += image.pixels[at + 1] ?? 0
          blue += image.pixels[at + 2] ?? 0
          count++
        }
      }
      const out = (y * width + x) * 3
      pixels[out] = Math.round(red / count)
      pixels[out + 1] = Math.round(green / count)
      pixels[out + 2] = Math.round(blue / count)
    }
  }
  return { width, height, pixels }
}

/** Median-cut palette plus one palette index per pixel. */
export function quantize(
  image: RgbImage,
  colors = 256,
): { palette: number[][]; indices: Uint8Array } {
  interface Bucket {
    key: number
    red: number
    green: number
    blue: number
    count: number
  }
  const buckets = new Map<number, Bucket>()
  for (let at = 0; at < image.pixels.length; at += 3) {
    const red = image.pixels[at] ?? 0
    const green = image.pixels[at + 1] ?? 0
    const blue = image.pixels[at + 2] ?? 0
    const key = ((red >> 3) << 10) | ((green >> 3) << 5) | (blue >> 3)
    const bucket = buckets.get(key)
    if (bucket) {
      bucket.red += red
      bucket.green += green
      bucket.blue += blue
      bucket.count++
    } else {
      buckets.set(key, { key, red, green, blue, count: 1 })
    }
  }
  const entries = [...buckets.values()]
  interface Box {
    start: number
    end: number
    weight: number
    spread: number
  }
  const measure = (start: number, end: number): Box => {
    let weight = 0
    let lowRed = 255
    let highRed = 0
    let lowGreen = 255
    let highGreen = 0
    let lowBlue = 255
    let highBlue = 0
    for (let index = start; index < end; index++) {
      const entry = entries[index] as Bucket
      const red = entry.red / entry.count
      const green = entry.green / entry.count
      const blue = entry.blue / entry.count
      weight += entry.count
      lowRed = Math.min(lowRed, red)
      highRed = Math.max(highRed, red)
      lowGreen = Math.min(lowGreen, green)
      highGreen = Math.max(highGreen, green)
      lowBlue = Math.min(lowBlue, blue)
      highBlue = Math.max(highBlue, blue)
    }
    return {
      start,
      end,
      weight,
      spread: Math.max(
        highRed - lowRed,
        highGreen - lowGreen,
        highBlue - lowBlue,
      ),
    }
  }
  let boxes: Box[] = [measure(0, entries.length)]
  while (boxes.length < colors) {
    let target: Box | undefined
    for (const box of boxes) {
      if (box.end - box.start < 2) continue
      if (!target || box.weight * box.spread > target.weight * target.spread)
        target = box
    }
    if (!target || target.spread === 0) break
    const box = target
    const channel = dominantChannel(entries, box.start, box.end)
    const slice = entries
      .slice(box.start, box.end)
      .map((entry) => ({
        entry,
        mean:
          (channel === 0
            ? entry.red
            : channel === 1
              ? entry.green
              : entry.blue) / entry.count,
      }))
      .sort((a, b) => a.mean - b.mean)
    for (let index = 0; index < slice.length; index++)
      entries[box.start + index] = (slice[index] as { entry: Bucket }).entry
    let split = box.start + 1
    let half = 0
    let total = 0
    for (let index = box.start; index < box.end; index++)
      total += (entries[index] as Bucket).count
    for (let index = box.start; index < box.end - 1; index++) {
      half += (entries[index] as Bucket).count
      split = index + 1
      if (half * 2 >= total) break
    }
    boxes = boxes.filter((item) => item !== box)
    boxes.push(measure(box.start, split), measure(split, box.end))
  }

  const palette: number[][] = []
  const colorByKey = new Map<number, number>()
  for (const box of boxes) {
    let red = 0
    let green = 0
    let blue = 0
    let count = 0
    for (let index = box.start; index < box.end; index++) {
      const entry = entries[index] as Bucket
      red += entry.red
      green += entry.green
      blue += entry.blue
      count += entry.count
    }
    const color: [number, number, number] = [
      Math.round(red / count),
      Math.round(green / count),
      Math.round(blue / count),
    ]
    const paletteIndex = palette.length
    if (paletteIndex < 256) palette.push(color)
    for (let index = box.start; index < box.end; index++)
      colorByKey.set((entries[index] as Bucket).key, paletteIndex)
  }

  const nearest = new Map<number, number>()
  const lookup = (key: number): number => {
    const cached = nearest.get(key)
    if (cached !== undefined) return cached
    const red = ((key >> 10) & 31) * 8
    const green = ((key >> 5) & 31) * 8
    const blue = (key & 31) * 8
    let best = 0
    let bestDistance = Number.POSITIVE_INFINITY
    for (let index = 0; index < palette.length; index++) {
      const color = palette[index] as number[]
      const dr = (color[0] as number) - red
      const dg = (color[1] as number) - green
      const db = (color[2] as number) - blue
      const distance = dr * dr + dg * dg + db * db
      if (distance < bestDistance) {
        bestDistance = distance
        best = index
      }
    }
    nearest.set(key, best)
    return best
  }

  const indices = new Uint8Array(image.width * image.height)
  for (let at = 0, pixel = 0; at < image.pixels.length; at += 3, pixel++) {
    const red = image.pixels[at] ?? 0
    const green = image.pixels[at + 1] ?? 0
    const blue = image.pixels[at + 2] ?? 0
    const key = ((red >> 3) << 10) | ((green >> 3) << 5) | (blue >> 3)
    indices[pixel] = colorByKey.get(key) ?? lookup(key)
  }
  return { palette, indices }
}

/** Encode indexed pixels as one DECSIXEL sequence. */
export function encodeSixel(
  image: RgbImage,
  palette: number[][],
  indices: Uint8Array,
): string {
  const parts: string[] = [`\x1bPq"1;1;${image.width};${image.height}`]
  for (let index = 0; index < palette.length; index++) {
    const color = palette[index] as number[]
    const percent = (value: number): number => Math.round((value * 100) / 255)
    parts.push(
      `#${index};2;${percent(color[0] as number)};${percent(color[1] as number)};${percent(color[2] as number)}`,
    )
  }
  const bands = Math.ceil(image.height / 6)
  const patterns = new Map<number, Uint8Array>()
  for (let band = 0; band < bands; band++) {
    const used: number[] = []
    for (let column = 0; column < image.width; column++) {
      for (let row = 0; row < 6; row++) {
        const y = band * 6 + row
        if (y >= image.height) break
        const index = indices[y * image.width + column] as number
        let pattern = patterns.get(index)
        if (!pattern) {
          pattern = new Uint8Array(image.width)
          patterns.set(index, pattern)
          used.push(index)
        }
        pattern[column] = (pattern[column] as number) | (1 << row)
      }
    }
    used.sort((a, b) => a - b)
    for (const index of used) {
      parts.push(`#${index}`)
      const pattern = patterns.get(index) as Uint8Array
      let run = 1
      let value = pattern[0] as number
      for (let column = 1; column <= image.width; column++) {
        const next = column < image.width ? (pattern[column] as number) : -1
        if (next === value) {
          run++
          continue
        }
        const character = String.fromCharCode(63 + value)
        parts.push(run > 3 ? `!${run}${character}` : character.repeat(run))
        value = next
        run = 1
      }
      parts.push('$')
      pattern.fill(0)
      patterns.delete(index)
    }
    if (band < bands - 1) parts.push('-')
  }
  parts.push('\x1b\\')
  return parts.join('')
}

const cache = new Map<string, SixelLines | null>()

/**
 * Render a base64 PNG as the lines of a pi tool row, or `null` when this
 * terminal, this MIME type, or this image cannot be drawn as sixel.
 */
export function renderSixelLines(
  base64: string,
  mimeType: string,
  options: SixelOptions = {},
  env: Env = process.env,
): SixelLines | null {
  if (mimeType.toLowerCase() !== 'image/png') return null
  if (!sixelSupported(env)) return null
  const maxWidthCells = options.maxWidthCells ?? DEFAULT_MAX_WIDTH_CELLS
  const maxHeightCells = options.maxHeightCells ?? DEFAULT_MAX_HEIGHT_CELLS
  const cellWidthPx = options.cellWidthPx ?? DEFAULT_CELL_WIDTH_PX
  const cellHeightPx = options.cellHeightPx ?? DEFAULT_CELL_HEIGHT_PX
  const key = `${createHash('sha1').update(base64).digest('hex')}|${maxWidthCells}x${maxHeightCells}`
  const cached = cache.get(key)
  if (cached !== undefined) return cached

  let rendered: SixelLines | null = null
  try {
    const decoded = decodePng(Buffer.from(base64, 'base64'))
    const fitted = downscale(
      decoded,
      maxWidthCells * cellWidthPx,
      maxHeightCells * cellHeightPx,
    )
    const { palette, indices } = quantize(fitted)
    const sequence = encodeSixel(fitted, palette, indices)
    const rows = Math.max(1, Math.ceil(fitted.height / cellHeightPx))
    const columns = Math.max(1, Math.ceil(fitted.width / cellWidthPx))
    const lines = Array.from({ length: rows - 1 }, () => '')
    const cursorUp = rows > 1 ? `\x1b[${rows - 1}A` : ''
    lines.push(`${cursorUp}${IMAGE_LINE_MARKER}${sequence}`)
    rendered = { lines, columns, rows }
  } catch {
    rendered = null
  }
  cache.set(key, rendered)
  while (cache.size > MAX_CACHE_ENTRIES) {
    const oldest = cache.keys().next().value
    if (oldest === undefined) break
    cache.delete(oldest)
  }
  return rendered
}

function readUint32(bytes: Uint8Array, offset: number): number {
  return (
    (((bytes[offset] ?? 0) << 24) |
      ((bytes[offset + 1] ?? 0) << 16) |
      ((bytes[offset + 2] ?? 0) << 8) |
      (bytes[offset + 3] ?? 0)) >>>
    0
  )
}

function unfilterRow(
  filter: number,
  row: Uint8Array,
  previous: Uint8Array,
  channels: number,
): void {
  const stride = row.length
  if (filter === 0) return
  if (filter === 1) {
    for (let index = channels; index < stride; index++) {
      row[index] =
        ((row[index] as number) + (row[index - channels] as number)) & 0xff
    }
    return
  }
  if (filter === 2) {
    for (let index = 0; index < stride; index++) {
      row[index] = ((row[index] as number) + (previous[index] as number)) & 0xff
    }
    return
  }
  if (filter === 3) {
    for (let index = 0; index < stride; index++) {
      const left = index >= channels ? (row[index - channels] as number) : 0
      row[index] =
        ((row[index] as number) + ((left + (previous[index] as number)) >> 1)) &
        0xff
    }
    return
  }
  if (filter === 4) {
    for (let index = 0; index < stride; index++) {
      const left = index >= channels ? (row[index - channels] as number) : 0
      const up = previous[index] as number
      const upperLeft =
        index >= channels ? (previous[index - channels] as number) : 0
      const estimate = left + up - upperLeft
      const da = Math.abs(estimate - left)
      const db = Math.abs(estimate - up)
      const dc = Math.abs(estimate - upperLeft)
      const predictor = da <= db && da <= dc ? left : db <= dc ? up : upperLeft
      row[index] = ((row[index] as number) + predictor) & 0xff
    }
    return
  }
  throw new Error(`unknown PNG filter ${filter}`)
}

function dominantChannel(
  entries: { red: number; green: number; blue: number; count: number }[],
  start: number,
  end: number,
): 0 | 1 | 2 {
  let lowRed = 255
  let highRed = 0
  let lowGreen = 255
  let highGreen = 0
  let lowBlue = 255
  let highBlue = 0
  for (let index = start; index < end; index++) {
    const entry = entries[index] as {
      red: number
      green: number
      blue: number
      count: number
    }
    const red = entry.red / entry.count
    const green = entry.green / entry.count
    const blue = entry.blue / entry.count
    lowRed = Math.min(lowRed, red)
    highRed = Math.max(highRed, red)
    lowGreen = Math.min(lowGreen, green)
    highGreen = Math.max(highGreen, green)
    lowBlue = Math.min(lowBlue, blue)
    highBlue = Math.max(highBlue, blue)
  }
  const spread = [highRed - lowRed, highGreen - lowGreen, highBlue - lowBlue]
  return spread.indexOf(Math.max(...spread)) as 0 | 1 | 2
}
