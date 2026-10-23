import { fireEvent, render, screen } from '@testing-library/react'
import { expect, it, vi } from 'vitest'
import ChatMarkdown from './ChatMarkdown'

it('routes source citations to document navigation and keeps external links safe', () => {
  const docId = 'a'.repeat(64)
  const openDocument = vi.fn()
  const openMolecule = vi.fn()
  render(<ChatMarkdown content={`[Source](#document/${docId}?page=2), [Ligand](#molecule/mol-1) and [External](https://example.com)`} onDocumentLink={openDocument} onMoleculeLink={openMolecule} />)
  fireEvent.click(screen.getByRole('link', { name: 'Source' }))
  expect(openDocument).toHaveBeenCalledWith(docId, 2)
  fireEvent.click(screen.getByRole('link', { name: 'Ligand' }))
  expect(openMolecule).toHaveBeenCalledWith('mol-1')
  expect(screen.getByRole('link', { name: 'External' })).toHaveAttribute('rel', 'noopener noreferrer')
  expect(screen.getByRole('link', { name: 'External' })).toHaveAttribute('target', '_blank')
})
