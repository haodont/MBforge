/**
 * R-Group 矩阵视图共享工具函数.
 *
 * 提供：
 * - activity (IC50/EC50) 单位归一化到 nM
 * - pIC50 (= -log10(M)) 计算 — 用于颜色映射
 * - 颜色插值 (红→黄→绿 = 低→高活性)
 * - SMILES / 活性数值展示格式化
 */

/** 根据 activity + units 计算 IC50 nM 归一化值。 */
export function activityToNM(
  activity: number | undefined,
  units: string | undefined,
): number | null {
  if (activity == null) return null
  if (units === 'uM' || units === 'μM') return activity * 1000
  if (units === 'mM') return activity * 1e6
  if (units === 'nM' || !units) return activity
  return activity
}

/** pIC50 = -log10(M) = 9 - log10(nM). 范围 0-12 覆盖 uM→pM. */
export function pActScale(
  activity: number | undefined,
  units: string | undefined,
): number | null {
  const nM = activityToNM(activity, units)
  if (nM == null || nM <= 0) return null
  return 9 - Math.log10(nM)
}

/** 颜色：从红（低 pIC50 = 弱）→ 黄 → 绿（高 pIC50 = 强）。 */
export function activityColor(pAct: number | null): string {
  if (pAct == null) return 'transparent'
  const p = Math.max(0, Math.min(12, pAct))
  const t = p / 12
  const r = Math.round(220 + t * (34 - 220) * Math.min(1, t * 2))
  const g = Math.round(38 + t * (197 - 38))
  const b = Math.round(38 + t * (94 - 38) * Math.min(1, (1 - t) * 2))
  return `rgb(${r}, ${g}, ${b})`
}

/** 截断 SMILES 展示。 */
export function shortSmiles(s: string, max = 18): string {
  if (!s || s === '—') return s || '—'
  return s.length > max ? `${s.slice(0, max - 1)}…` : s
}

/** 格式化活性数值。 */
export function formatActivity(
  value: number | undefined,
  units: string | undefined,
): string {
  if (value == null) return '—'
  const formatted = value < 0.01 ? value.toFixed(3) : value.toFixed(2)
  return `${formatted} ${units ?? ''}`
}
