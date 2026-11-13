// @tested-functions sixelSupported decodePng renderSixelLines
import assert from 'node:assert/strict'
import test from 'node:test'
import { deflateSync, crc32 } from 'node:zlib'

// Deep imports: these are the exact predicates pi applies to a rendered line,
// so the test fails loudly if a pi upgrade stops exempting our image line.
import { isImageLine } from '@earendil-works/pi-tui/dist/terminal-image.js'
import { visibleWidth } from '@earendil-works/pi-tui/dist/utils.js'

import {
  IMAGE_LINE_MARKER,
  decodePng,
  renderSixelLines,
  sixelSupported,
} from './terminalImage.js'

/** A PNG whose first row uses filter 0 and the rest filter 2, so the decoder's
 *  unfiltering is exercised against a real stream rather than raw rows. */
function png(
  width: number,
  height: number,
  color: (x: number, y: number) => [number, number, number, number?],
): string {
  const stride = width * 4
  const raw = Buffer.alloc((stride + 1) * height)
  let previous = Buffer.alloc(stride)
  for (let y = 0; y < height; y++) {
    const at = y * (stride + 1)
    raw[at] = y === 0 ? 0 : 2
    const row = Buffer.alloc(stride)
    for (let x = 0; x < width; x++) {
      const [red, green, blue, alpha = 255] = color(x, y)
      row.set([red, green, blue, alpha], x * 4)
    }
    for (let index = 0; index < stride; index++) {
      raw[at + 1 + index] =
        y === 0
          ? (row[index] as number)
          : ((row[index] as number) - (previous[index] as number)) & 0xff
    }
    previous = row
  }
  const chunk = (type: string, data: Buffer): Buffer => {
    const head = Buffer.alloc(4)
    head.writeUInt32BE(data.length)
    const body = Buffer.concat([Buffer.from(type, 'ascii'), data])
    const tail = Buffer.alloc(4)
    tail.writeUInt32BE(crc32(body))
    return Buffer.concat([head, body, tail])
  }
  const header = Buffer.alloc(13)
  header.writeUInt32BE(width, 0)
  header.writeUInt32BE(height, 4)
  header[8] = 8
  header[9] = 6
  return Buffer.concat([
    Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]),
    chunk('IHDR', header),
    chunk('IDAT', deflateSync(raw)),
    chunk('IEND', Buffer.alloc(0)),
  ]).toString('base64')
}

test('sixel is enabled only on terminals pi reports as image-less but that speak sixel', () => {
  assert.equal(sixelSupported({}), false)
  assert.equal(
    sixelSupported({ WT_SESSION: '1', TERM_PROGRAM_VERSION: '1.22.0' }),
    true,
  )
  assert.equal(
    sixelSupported({ WT_SESSION: '1', TERM_PROGRAM_VERSION: '1.21.0' }),
    false,
  )
  assert.equal(sixelSupported({ TERM: 'xterm-sixel' }), true)
  assert.equal(sixelSupported({ PI_IMAGE_PROTOCOL: 'sixel' }), true)
  assert.equal(
    sixelSupported({ PI_IMAGE_PROTOCOL: 'none', TERM: 'xterm-sixel' }),
    false,
  )
  // A Kitty terminal takes pi's own path; do not draw the same image twice.
  assert.equal(sixelSupported({ KITTY_WINDOW_ID: '1' }), false)
})

test('a png with filtered rows and transparency decodes to the composited pixels', () => {
  const image = decodePng(
    Buffer.from(
      png(2, 3, (x) => (x === 0 ? [255, 0, 0, 255] : [0, 0, 0, 0])),
      'base64',
    ),
  )
  assert.equal(image.width, 2)
  assert.equal(image.height, 3)
  // Row 2 is filter-2 encoded, so a wrong unfilter shows as a repeated row.
  for (let y = 0; y < 3; y++) {
    const at = y * 2 * 3
    assert.deepEqual([...image.pixels.subarray(at, at + 3)], [255, 0, 0])
    assert.deepEqual(
      [...image.pixels.subarray(at + 3, at + 6)],
      [255, 255, 255],
    )
  }
})

test('a rendered image becomes one sixel line pi will not slice, over reserved rows', () => {
  const data = png(40, 30, (x) => (x < 20 ? [0, 0, 0] : [255, 255, 255]))
  const rendered = renderSixelLines(
    data,
    'image/png',
    {},
    { TERM: 'xterm-sixel' },
  )
  assert.ok(rendered, 'the image encodes')
  assert.equal(rendered.rows, 2, '30 px over an 18 px cell is two rows')
  assert.equal(rendered.lines.length, rendered.rows)
  assert.deepEqual(rendered.lines.slice(0, -1), [''])

  const drawn = rendered.lines.at(-1) as string
  assert.ok(
    drawn.startsWith(`\x1b[${rendered.rows - 1}A${IMAGE_LINE_MARKER}\x1bPq`),
    drawn.slice(0, 40),
  )
  assert.ok(drawn.endsWith('\x1b\\'))
  // pi slices every line wider than the terminal unless it is an image line;
  // the marker is the only reason this 40-column image survives at width 20.
  assert.ok(isImageLine(drawn))
  assert.ok(visibleWidth(drawn) > 20)
})

test('an oversized page render is scaled into the cell box instead of emitted at full width', () => {
  const data = png(400, 300, () => [0, 0, 0])
  const rendered = renderSixelLines(
    data,
    'image/png',
    {},
    { TERM: 'xterm-sixel' },
  )
  assert.ok(rendered)
  assert.ok(rendered.columns <= 72)
  assert.ok(rendered.rows <= 24)
  assert.equal(
    renderSixelLines(data, 'image/jpeg', {}, { TERM: 'xterm-sixel' }),
    null,
  )
})
