/**
 * ROI 文本提取 — 从 PDF 页面文本中提取检测框周围的上下文文本
 *
 * pdf.js 提供的文本项带有 PDF 坐标（x, y, width, height），
 * 检测框也有 PDF 坐标（bbox_pdf: [x1, y1, x2, y2]）。
 * 此函数找出与检测框相交的文本项，拼接为上下文。
 */

export interface TextItem {
  str: string
  x: number
  y: number
  width: number
  height: number
}

/** 判断两个矩形是否相交 */
function rectsIntersect(
  ax: number, ay: number, aw: number, ah: number,
  bx: number, by: number, bw: number, bh: number,
): boolean {
  return ax < bx + bw && ax + aw > bx && ay < by + bh && ay + ah > by
}

/**
 * 提取检测框周围的上下文文本
 *
 * @param bboxPdf - 检测框 [x1, y1, x2, y2]（PDF points，左下角原点）
 * @param pageTextItems - 当前页的所有文本项（PDF points，左下角原点）
 * @param pageHeight - 页面高度（PDF points）
 * @param expandPx - 向外扩展的像素数（PDF points），默认 20pt
 * @returns 拼接的上下文文本
 */
export function extractRoiText(
  bboxPdf: [number, number, number, number],
  pageTextItems: TextItem[],
  _pageHeight: number,
  expandPx: number = 20,
): string {
  const [x1, y1, x2, y2] = bboxPdf

  // 扩展检测框（上下左右各 expandPx）
  const ex1 = x1 - expandPx
  const ey1 = y1 - expandPx
  const ex2 = x2 + expandPx
  const ey2 = y2 + expandPx
  const ew = ex2 - ex1
  const eh = ey2 - ey1

  // 找出与扩展框相交的文本项
  const overlapping: { item: TextItem; dist: number }[] = []

  for (const item of pageTextItems) {
    // pdf.js 的 y 坐标是左下角原点，与 bbox_pdf 一致
    if (rectsIntersect(ex1, ey1, ew, eh, item.x, item.y, item.width, item.height)) {
      // 计算到检测框中心的距离（用于排序）
      const cx = x1 + (x2 - x1) / 2
      const cy = y1 + (y2 - y1) / 2
      const ix = item.x + item.width / 2
      const iy = item.y + item.height / 2
      const dist = Math.sqrt((cx - ix) ** 2 + (cy - iy) ** 2)
      overlapping.push({ item, dist })
    }
  }

  // 按距离排序（最近的在前）
  overlapping.sort((a, b) => a.dist - b.dist)

  // 拼接文本（最多取 500 字符）
  const texts = overlapping.map(o => o.item.str.trim()).filter(t => t.length > 0)
  const full = texts.join(' ')
  return full.length > 500 ? full.slice(0, 500) + '...' : full
}
