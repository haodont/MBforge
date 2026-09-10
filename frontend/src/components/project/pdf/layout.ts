import type { ExtractionResult } from '@/types'
import type { OcrBlock } from '@/api/http/pdf'

export interface TextItem {
  str: string
  x: number
  y: number
  width: number
  height: number
}

export interface TextBlock {
  type: 'text'
  sortY: number
  text: string
}

export interface MoleculeBlock {
  type: 'molecule'
  sortY: number
  mol: ExtractionResult & { _originalIndex: number }
  originalIndex: number
}

export type ContentBlock = TextBlock | MoleculeBlock

// 文本行高度估算
export const LINE_HEIGHT = 28
// 分子卡片高度
export const MOL_CARD_HEIGHT = 120

/**
 * 把 text items 按 y 坐标聚合成行（OCR 感知）。
 *
 * - 有当前页的 OCR text blocks：按 OCR 块的 bbox 把 items 归到对应段落（语义边界 = 段落），
 *   段内按 y 阈值分行。OCR 块作为更强的语义边界，避免标题/正文/页眉被错误合并。
 * - 无 OCR blocks：fallback 到纯 y 阈值分行启发式（与旧版一致）。
 *
 * 坐标语义：PDF text item.y 是 PDF bottom-left origin 的 baseline；OcrBlock.bbox
 * 是 backend 已做 top-left → bottom-left 翻转后的 PDF points bottom-left origin
 * （见 services/documents/pdf_layout.py 的坐标翻转契约）。
 */
export function groupTextLines(
  items: TextItem[],
  ocrTextBlocks: OcrBlock[] = [],
): { text: string; y: number }[] {
  if (items.length === 0) return []

  if (ocrTextBlocks.length === 0) {
    // 无 OCR：纯 y 排序 + 阈值分行
    return groupByYThreshold(items)
  }

  // OCR 感知：按 OCR text block bbox 把 items 归段，再段内分行
  // bbox[1] = 块底 y（PDF bottom-left origin）；越大越靠上 → 降序 = 上→下
  const sortedBlocks = [...ocrTextBlocks].sort((a, b) => b.bbox[1] - a.bbox[1])
  const used = new Set<TextItem>()
  const lines: { text: string; y: number }[] = []

  for (const block of sortedBlocks) {
    const [x1, y1, x2, y2] = block.bbox
    const inBlock = items.filter((it) => {
      if (used.has(it)) return false
      const cx = it.x + it.width / 2
      const cy = it.y
      // 边界 ±3pt 容差，避免边缘 item 漏分到相邻块
      return cx >= x1 - 3 && cx <= x2 + 3 && cy >= y1 - 3 && cy <= y2 + 3
    })
    if (inBlock.length === 0) continue
    inBlock.forEach((it) => used.add(it))
    for (const line of groupByYThreshold(inBlock)) {
      lines.push(line)
    }
  }

  // 剩余 items（不在任何 OCR 块内的）：按 y 排序 + 阈值分行，追加在末尾
  const leftovers = items.filter((it) => !used.has(it))
  if (leftovers.length > 0) {
    for (const line of groupByYThreshold(leftovers)) {
      lines.push(line)
    }
  }

  // 整体按 y 降序（顶部优先）
  lines.sort((a, b) => b.y - a.y)
  return lines
}

/** 纯 y 排序 + 阈值分行的兜底实现（item.y 差 > 6pt 视为新行） */
function groupByYThreshold(items: TextItem[]): { text: string; y: number }[] {
  if (items.length === 0) return []
  const sorted = [...items].sort((a, b) => {
    const dy = b.y - a.y
    if (Math.abs(dy) > 6) return dy
    return a.x - b.x
  })
  const lines: { text: string; y: number }[] = []
  let currentParts: string[] = []
  let currentY = sorted[0].y
  for (const item of sorted) {
    if (Math.abs(item.y - currentY) > 6) {
      if (currentParts.length > 0) {
        lines.push({ text: currentParts.join(' ').trim(), y: currentY })
      }
      currentParts = [item.str]
      currentY = item.y
    } else {
      currentParts.push(item.str)
    }
  }
  if (currentParts.length > 0) {
    lines.push({ text: currentParts.join(' ').trim(), y: currentY })
  }
  return lines.filter(l => l.text.length > 0)
}

/** 将文本行和分子检测按 y 坐标交错排列 */
export function buildContentStream(
  textItems: TextItem[],
  detections: (ExtractionResult & { _originalIndex: number })[],
  ocrTextBlocks: OcrBlock[] = [],
): ContentBlock[] {
  const lines = groupTextLines(textItems, ocrTextBlocks)
  const blocks: ContentBlock[] = []

  for (const line of lines) {
    blocks.push({ type: 'text', sortY: line.y, text: line.text })
  }

  for (const mol of detections) {
    const y = mol.bbox_pdf?.[1] ?? 0
    blocks.push({ type: 'molecule', sortY: y, mol, originalIndex: mol._originalIndex })
  }

  // 按 y 降序排列（PDF 坐标系：y 越大越靠页面顶部）
  blocks.sort((a, b) => b.sortY - a.sortY)
  return blocks
}

/** 估算每个 block 的像素高度 */
export function estimateBlockHeight(block: ContentBlock): number {
  if (block.type === 'text') {
    const lineCount = Math.max(1, Math.ceil(block.text.length / 50))
    return lineCount * LINE_HEIGHT + 12 // padding
  }
  return MOL_CARD_HEIGHT
}
