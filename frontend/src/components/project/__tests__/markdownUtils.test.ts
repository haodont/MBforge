import { describe, expect, it } from 'vitest'
import { cleanMoleculePlaceholders, rewriteImageUrls } from '../markdownUtils'

describe('cleanMoleculePlaceholders', () => {
  it('removes internal unavailable-structure blocks while preserving document content', () => {
    const markdown = [
      '# Results',
      '',
      'Compound A was reported.',
      '',
      '```molecode',
      'MoleCode not available for Mol_001',
      '```',
      '',
      '## Discussion',
      '',
      'The activity was confirmed.',
    ].join('\n')

    expect(cleanMoleculePlaceholders(markdown)).toBe([
      '# Results',
      '',
      'Compound A was reported.',
      '',
      '## Discussion',
      '',
      'The activity was confirmed.',
    ].join('\n'))
  })

  it('removes a placeholder-only document', () => {
    expect(cleanMoleculePlaceholders('```\nStructure not generated for Mol_002\n```')).toBe('')
  })
})

describe('rewriteImageUrls', () => {
  it('rewrites OCR-backend relative image URLs to backend endpoint URLs', () => {
    const markdown = '![](images/abc.jpg)'
    const docId = 'doc123'
    const libraryRoot = '/tmp/lib'
    const expected = `![](/api/v1/library/documents/${encodeURIComponent(docId)}/images/${encodeURIComponent('abc.jpg')}?library_root=${encodeURIComponent(libraryRoot)})`
    expect(rewriteImageUrls(markdown, docId, libraryRoot)).toBe(expected)
  })

  it('preserves alt text when rewriting image URLs', () => {
    const markdown = '![figure caption](images/abc.png)'
    const docId = 'doc123'
    const libraryRoot = '/tmp/lib'
    const expected = `![figure caption](/api/v1/library/documents/${encodeURIComponent(docId)}/images/${encodeURIComponent('abc.png')}?library_root=${encodeURIComponent(libraryRoot)})`
    expect(rewriteImageUrls(markdown, docId, libraryRoot)).toBe(expected)
  })

  it('rewrites multiple image references', () => {
    const markdown = '![](images/a.jpg)\n\n![b](images/b.png)'
    const result = rewriteImageUrls(markdown, 'doc123', '/tmp/lib')
    expect(result).toContain('/api/v1/library/documents/doc123/images/a.jpg?library_root=%2Ftmp%2Flib')
    expect(result).toContain('/api/v1/library/documents/doc123/images/b.png?library_root=%2Ftmp%2Flib')
  })

  it('leaves non-images markdown unchanged', () => {
    const markdown = '[link](https://example.com)'
    expect(rewriteImageUrls(markdown, 'doc123', '/tmp/lib')).toBe(markdown)
  })
})
