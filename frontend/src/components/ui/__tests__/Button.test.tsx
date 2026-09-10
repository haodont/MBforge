import { describe, it, expect } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import Button from '../Button'

describe('Button', () => {
  it('calls onClick when clicked', () => {
    const onClick = vi.fn()
    render(<Button onClick={onClick}>Click</Button>)
    fireEvent.click(screen.getByText('Click'))
    expect(onClick).toHaveBeenCalledOnce()
  })

  it('is disabled when disabled prop is true', () => {
    const onClick = vi.fn()
    render(<Button disabled onClick={onClick}>Click</Button>)
    const btn = screen.getByText('Click').closest('button')
    expect(btn).toBeDisabled()
    fireEvent.click(btn as HTMLElement)
    expect(onClick).not.toHaveBeenCalled()
  })

  it('shows loading spinner and prevents click', () => {
    const onClick = vi.fn()
    render(<Button loading onClick={onClick}>Load</Button>)
    const btn = screen.getByText('Load').closest('button')
    expect(btn).toBeDisabled()
    expect(btn?.querySelector('span')).toBeInTheDocument()
    fireEvent.click(btn as HTMLElement)
    expect(onClick).not.toHaveBeenCalled()
  })

  it('renders icon alongside children', () => {
    render(<Button icon={<span data-testid="icon">🔍</span>}>Search</Button>)
    expect(screen.getByTestId('icon')).toBeInTheDocument()
    expect(screen.getByText('Search')).toBeInTheDocument()
  })

  it('renders with type attribute', () => {
    render(<Button type="submit">Submit</Button>)
    expect(screen.getByText('Submit').closest('button')).toHaveAttribute('type', 'submit')
  })

  it('sets title attribute', () => {
    render(<Button title="tooltip">Hover</Button>)
    expect(screen.getByText('Hover').closest('button')).toHaveAttribute('title', 'tooltip')
  })

  it('defaults to type button', () => {
    render(<Button>Default</Button>)
    expect(screen.getByText('Default').closest('button')).toHaveAttribute('type', 'button')
  })
})
