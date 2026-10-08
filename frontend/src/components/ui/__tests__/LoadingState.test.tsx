import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { LoadingState } from '../LoadingState'

describe('LoadingState', () => {
  it('renders spinner variant', () => {
    render(<LoadingState variant="spinner" message="Loading..." />)
    expect(screen.getByText('Loading...')).toBeInTheDocument()
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
