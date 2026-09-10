import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { LoadingState } from '../LoadingState'

describe('LoadingState', () => {
  it('renders spinner variant', () => {
    render(<LoadingState variant="spinner" message="Loading..." />)
    expect(screen.getByText('Loading...')).toBeInTheDocument()
  })

  it('renders skeleton variant', () => {
    const { container } = render(<LoadingState variant="skeleton" count={3} />)
    // Skeleton renders the correct number of skeleton divs.
    const skeletonItems = container.querySelectorAll('.loading-state-skeleton > div')
    expect(skeletonItems.length).toBe(3)
  })

  it('renders progress variant', () => {
    render(<LoadingState variant="progress" progress={65} progressLabel="Indexing..." />)
    expect(screen.getByText('Indexing...')).toBeInTheDocument()
  })

  it('renders message with spinner', () => {
    render(<LoadingState message="Please wait" />)
    expect(screen.getByText('Please wait')).toBeInTheDocument()
  })
})
