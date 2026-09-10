import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { normalizePatentLatex, renderInlineLatex } from '../chatUtils'

describe('renderInlineLatex', () => {
  it('renders inline math', () => {
    render(<span>{renderInlineLatex('Energy $E=mc^2$ value')}</span>)
    expect(screen.getByText(/Energy/)).toBeInTheDocument()
    expect(document.querySelector('.katex')).toBeInTheDocument()
  })

  it('renders patent-style grouped formulas', () => {
    render(<span>{renderInlineLatex('$\\mathbb{R}^9$ 取代基取代； $\\mathrm{C}{1 - 4}$ 卤代烷基')}</span>)
    expect(document.querySelectorAll('.katex')).toHaveLength(2)
  })

  it('renders formulas after ReactMarkdown parses the paragraph', () => {
    render(
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{ p: ({ children }) => <p>{renderInlineLatex(children)}</p> }}
      >
        {'$\\mathbb{R}^9$ 取代基取代； $\\mathrm{C}{1 - 4}$ 卤代烷基'}
      </ReactMarkdown>,
    )
    expect(document.querySelectorAll('.katex')).toHaveLength(2)
  })

  it('normalizes escaped patent markdown formulas', () => {
    render(<span>{renderInlineLatex('\\$\\\\mathbb{R}^9\\$')}</span>)
    expect(document.querySelector('.katex')).toBeInTheDocument()
  })

  it('normalizes patent carbon-range notation to a subscript', () => {
    render(<span>{renderInlineLatex('$\\mathrm{C}{3 - 6}$')}</span>)
    expect(document.querySelector('.katex')).toBeInTheDocument()
  })

  it('renders patent formulas with a missing opening delimiter', () => {
    render(<span>{renderInlineLatex('\\mathrm{C(O)OR^f}、\\mathrm{C(O)NR^{d}R^{d}}$、或 $\\\\mathrm{NR^{d}S(O)2R^{g}}$')}</span>)
    expect(document.querySelectorAll('.katex').length).toBeGreaterThanOrEqual(3)
  })

  it('normalizes OCR chemistry notation before rendering', () => {
    expect(normalizePatentLatex('\\\\mathrm{C*{3 - 6}}、\\mathrm{S(O)*2R^{g}}')).toBe(
      '\\mathrm{C}_{3 - 6}、\\mathrm{S(O)2R^{g}}',
    )
  })

  it('renders display math', () => {
    render(<span>{renderInlineLatex('$$\\frac{1}{2}$$')}</span>)
    expect(document.querySelector('.katex-display')).toBeInTheDocument()
  })

  it('sanitizes injected script tags inside math', () => {
    render(<span>{renderInlineLatex('$\\href{javascript:alert(1)}{x}$')}</span>)
    expect(document.querySelector('script')).not.toBeInTheDocument()
  })
})
