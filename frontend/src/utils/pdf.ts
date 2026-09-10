/** 将 PDF 坐标（左下角原点）转换为 CSS 像素坐标（左上角原点） */
export function pdfToCss(
  bbox: [number, number, number, number],
  pageHeightPts: number,
  scale: number,
  pageWidthPts?: number,
  renderWidth?: number,
): { x: number; y: number; w: number; h: number } {
  const [x1, y1, x2, y2] = bbox
  const pdfW = x2 - x1
  const pdfH = y2 - y1
  // PDF 坐标系：左下角原点，Y 向上
  // CSS 坐标系：左上角原点，Y 向下
  const xScale = pageWidthPts && renderWidth ? renderWidth / pageWidthPts : scale
  const yScale = scale
  const cssX = x1 * xScale
  const cssY = (pageHeightPts - y2) * yScale
  const cssW = pdfW * xScale
  const cssH = pdfH * yScale
  return { x: cssX, y: cssY, w: cssW, h: cssH }
}
