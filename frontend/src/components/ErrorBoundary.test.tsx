import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, fireEvent, cleanup } from '@testing-library/react'
import { ErrorBoundary } from './ErrorBoundary'

function Boom(): never {
  throw new Error('kaboom')
}

afterEach(cleanup)

describe('ErrorBoundary', () => {
  afterEach(() => vi.restoreAllMocks())

  it('renders children when no error is thrown', () => {
    render(
      <ErrorBoundary>
        <span>healthy content</span>
      </ErrorBoundary>,
    )
    expect(screen.getByText('healthy content')).toBeInTheDocument()
  })

  it('renders the default fallback when a child throws', () => {
    vi.spyOn(console, 'error').mockImplementation(() => {})
    render(
      <ErrorBoundary>
        <Boom />
      </ErrorBoundary>,
    )
    expect(screen.getByRole('alert')).toBeInTheDocument()
    expect(screen.getByText(/something went wrong/i)).toBeInTheDocument()
  })

  it('renders a custom fallback when provided', () => {
    vi.spyOn(console, 'error').mockImplementation(() => {})
    render(
      <ErrorBoundary fallback={<span>custom fallback</span>}>
        <Boom />
      </ErrorBoundary>,
    )
    expect(screen.getByText('custom fallback')).toBeInTheDocument()
  })

  it('recovers when "Try again" is clicked and the subtree no longer throws', () => {
    vi.spyOn(console, 'error').mockImplementation(() => {})
    let shouldThrow = true
    function Maybe() {
      if (shouldThrow) throw new Error('kaboom')
      return <span>recovered</span>
    }
    render(
      <ErrorBoundary>
        <Maybe />
      </ErrorBoundary>,
    )
    expect(screen.getByRole('alert')).toBeInTheDocument()
    shouldThrow = false
    fireEvent.click(screen.getByRole('button', { name: /try again/i }))
    expect(screen.getByText('recovered')).toBeInTheDocument()
  })
})
