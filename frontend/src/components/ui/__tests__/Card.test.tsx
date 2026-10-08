import { describe, it, expect } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import Card from '../Card'

describe('Card', () => {
  it('renders children', () => {
    render(<Card><span data-testid="child">content</span></Card>)
    expect(screen.getByTestId('child')).toBeInTheDocument()
  })

  it('calls onClick when clicked', () => {
    const onClick = vi.fn()
    render(<Card onClick={onClick}>click</Card>)
    fireEvent.click(screen.getByText('click'))
    expect(onClick).toHaveBeenCalledOnce()
  })
})
