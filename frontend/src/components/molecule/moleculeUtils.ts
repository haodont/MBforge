/** SMILES → PubChem 图片 URL（最简方案，无需后端）*/
/** SMILES 基础验证：检查字符集（前端快速失败，与后端 chematic 解析互补）*/
export function basicValidate(smiles: string): { valid: boolean; message?: string } {
  if (!smiles || smiles.trim().length === 0) {
    return { valid: false, message: 'SMILES 为空' }
  }
  if (smiles.length > 200) {
    return { valid: false, message: 'SMILES 过长（>200字符）' }
  }
  // `*` is a valid RDKit wildcard atom used for Markush attachment points.
  if (!/^[A-Za-z0-9*@+\-[\]()\\/#%=.:]+$/.test(smiles.trim())) {
    return { valid: false, message: '包含非法字符' }
  }
  return { valid: true }
}

/** 估算分子式（非常简化版）*/
export function estimateFormula(smiles: string): string {
  const atomRegex = /[A-Z][a-z]?/g
  const atoms = new Map<string, number>()
  let match
  while ((match = atomRegex.exec(smiles)) !== null) {
    const atom = match[0]
    if (['Cl', 'Br'].includes(atom)) continue
    if (atom === 'H') continue // 隐式 H
    atoms.set(atom, (atoms.get(atom) ?? 0) + 1)
  }
  if (atoms.size === 0) return smiles
  return Array.from(atoms.entries())
    .sort(([a], [b]) => {
      if (a === 'C') return -1
      if (b === 'C') return 1
      return a.localeCompare(b)
    })
    .map(([atom, count]) => `${atom}${count > 1 ? count : ''}`)
    .join('')
}

const ATOMIC_WEIGHTS: Record<string, number> = {
  H: 1.008, C: 12.011, N: 14.007, O: 15.999,
  F: 18.998, P: 30.974, S: 32.065, Cl: 35.453,
  Br: 79.904, I: 126.904,
}

/** 估算分子量（粗略）*/
export function estimateMW(smiles: string): number {
  const atomRegex = /[A-Z][a-z]?/g
  let mw = 0
  let match
  while ((match = atomRegex.exec(smiles)) !== null) {
    const atom = match[0]
    if (atom === 'H') continue
    mw += ATOMIC_WEIGHTS[atom] ?? 0
  }
  return Math.round(mw * 10) / 10
}

/**
 * 化合物标识 → 匹配键（唯一实现）。
 *
 * 原先私有在 MoleculePatentFacts 里；分子详情面板需要同一推导，所以放这里而不是复制一份。
 */
export function compoundLabelKey(value: string): string {
  const cleaned = value
    .normalize('NFKC')
    .trim()
    .replace(/^(?:化合物|compound|cmpd|cpd|mol(?:ecule)?)[#_\-\s]*/i, '')
    .replace(/\s+/g, '')
  const match = /^(\d+[a-z]?)$/i.exec(cleaned)
  return (match?.[1] ?? cleaned).toLowerCase()
}

/**
 * 标签在事实工件里的键空间：`实施例7` / `Example 7` 属实施例空间（`@example:7`），
 * 裸 `化合物7` 属化合物空间。与后端 designation_key 同一套规则。
 */
export function designationsFor(label: string): string[] {
  const cleaned = label.normalize('NFKC').trim()
  const example =
    /^(?:example|实施例|実施例|制备例)\s*[#:：]?\s*([0-9]+[a-z]?(?:-[a-z0-9]+)?)$/i.exec(
      cleaned,
    )
  if (example) return [`@example:${example[1].toLowerCase()}`]
  const key = compoundLabelKey(cleaned)
  return key ? [key] : []
}
