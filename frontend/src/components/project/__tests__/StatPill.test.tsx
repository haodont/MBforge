import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { StatPill } from '../StatPill'

describe('StatPill', () => {
  it('renders label and value', () => {
    render(<StatPill label="Total" value={42} tone="neutral" />)
    expect(screen.getByText('Total')).toBeInTheDocument()
    expect(screen.getByText('42')).toBeInTheDocument()
  })

  it('renders icon when provided', () => {
    render(<StatPill label="Active" value={5} tone="info" icon={<span data-testid="icon">●</span>} />)
    expect(screen.getByTestId('icon')).toBeInTheDocument()
  })
})
