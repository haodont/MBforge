import katex from 'katex'
import DOMPurify from 'dompurify'

/** Normalize common OCR/LLM mutations in patent chemistry formulas. */
export function normalizePatentLatex(formula: string): string {
  return formula
    .replace(/\\\\(?=[A-Za-z])/g, '\\')
    // OCR emits C{1 - 4} / C*{3 - 6}; make the range a real subscript.
    .replace(/\\mathrm\{([A-Za-z]+)\*?\{\s*([^{}]+?)\s*\}\}/g, '\\mathrm{$1}_{$2}')
    .replace(/\\mathrm\{([A-Za-z]+)\}\{\s*([^{}]+?)\s*\}/g, '\\mathrm{$1}_{$2}')
    // In S(O)*2, the star is an OCR artefact, not a multiplication marker.
    .replace(/(?<=\))\s*\*\s*(?=\d)/g, '')
    .replace(/\s*([−–])\s*/g, '-')
    .replace(/\s{2,}/g, ' ')
    .trim()
}

/** Render inline/display LaTeX ($...$ / $$...$$) within React children. */
export function renderInlineLatex(children: React.ReactNode): React.ReactNode {
  if (typeof children === 'string') {
    const parts: React.ReactNode[] = []
    // Normalize escaped delimiters and doubled command slashes before KaTeX.
    const normalized = children
      .replace(/\\(?=\$)/g, '')
      .replace(/\\\\(?=(?:mathrm|mathbb)\b)/g, '\\')
    // Patent OCR sometimes drops the opening `$` but keeps the closing one.
    // Wrap bare \mathrm/\mathbb atoms in the text portions so the remaining
    // delimiter-based parser can render them without changing normal prose.
    const bareAtom = /\\(?:mathrm|mathbb)\{(?:[^{}]|\{[^{}]*\})+\}(?:\^\{[^{}]*\}|\^\w+)?/g
    const balanced = normalized
      .split('$')
      .map((part, index) => index % 2 === 0 ? part.replace(bareAtom, '$$$&$') : part)
      .join('$')
    const regex = /(\$\$[\s\S]+?\$\$|\$[^$\n]+?\$)/g
    let lastIndex = 0
    let match: RegExpExecArray | null
    while ((match = regex.exec(balanced)) !== null) {
      if (match.index > lastIndex) {
        parts.push(balanced.slice(lastIndex, match.index))
      }
      const displayMode = match[0].startsWith('$$')
      const formula = normalizePatentLatex(match[0]
        .slice(displayMode ? 2 : 1, displayMode ? -2 : -1)
      )
      if (formula) {
        try {
          const html = katex.renderToString(formula, { displayMode, throwOnError: false, trust: false })
          const safeHtml = DOMPurify.sanitize(html, { USE_PROFILES: { html: true } })
          parts.push(
            <span key={match.index} dangerouslySetInnerHTML={{ __html: safeHtml }} />
          )
        } catch {
          parts.push(<code key={match.index}>{formula}</code>)
        }
      }
      lastIndex = match.index + match[0].length
    }
    if (lastIndex < balanced.length) {
      parts.push(balanced.slice(lastIndex))
    }
    return parts.length > 0 ? <>{parts}</> : children
  }
  if (Array.isArray(children)) {
    return children.map((child: React.ReactNode, i: number) => (
      <span key={i}>{renderInlineLatex(child)}</span>
    ))
  }
  return children
}

/** 判断字符串是否为合法 SMILES */
export function isSmiles(s: string): boolean {
  if (!s || s.length < 2 || s.length > 200) return false
  const trimmed = s.trim()
  if (trimmed.startsWith('/') || trimmed.includes('../') || trimmed.includes('..\\')) return false
  if (!/^[A-Za-z0-9@+\-[\]()\\/#%=.:]+$/.test(trimmed)) return false
  if (/\.\w{2,4}$/.test(trimmed)) return false
  if (!/[0-9[\]()=#@+\-\\/]/.test(trimmed)) return false
  return true
}

/** SMILES → PubChem 图片 URL */
export function smilesToImgUrl(smiles: string): string {
  return `https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/smiles/${encodeURIComponent(smiles)}/PNG?image_size=300x300`
}
