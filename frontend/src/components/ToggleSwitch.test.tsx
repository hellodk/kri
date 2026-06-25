import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, fireEvent, cleanup } from '@testing-library/react'
import { ToggleSwitch } from './ToggleSwitch'

afterEach(cleanup)

describe('ToggleSwitch', () => {
  it('exposes switch role with aria-checked reflecting checked', () => {
    render(<ToggleSwitch checked={true} onChange={() => {}} ariaLabel="Enabled" />)
    const sw = screen.getByRole('switch', { name: 'Enabled' })
    expect(sw).toHaveAttribute('aria-checked', 'true')
  })

  it('reflects unchecked state', () => {
    render(<ToggleSwitch checked={false} onChange={() => {}} ariaLabel="Enabled" />)
    expect(screen.getByRole('switch')).toHaveAttribute('aria-checked', 'false')
  })

  it('calls onChange when clicked', () => {
    const onChange = vi.fn()
    render(<ToggleSwitch checked={false} onChange={onChange} ariaLabel="Enabled" />)
    fireEvent.click(screen.getByRole('switch'))
    expect(onChange).toHaveBeenCalledTimes(1)
  })

  it('does not call onChange when disabled', () => {
    const onChange = vi.fn()
    render(<ToggleSwitch checked={false} onChange={onChange} disabled ariaLabel="Enabled" />)
    const sw = screen.getByRole('switch')
    expect(sw).toBeDisabled()
    fireEvent.click(sw)
    expect(onChange).not.toHaveBeenCalled()
  })

  it('is disabled and marked busy while loading', () => {
    const onChange = vi.fn()
    render(<ToggleSwitch checked={true} onChange={onChange} loading ariaLabel="Enabled" />)
    const sw = screen.getByRole('switch')
    expect(sw).toBeDisabled()
    expect(sw).toHaveAttribute('aria-busy', 'true')
    fireEvent.click(sw)
    expect(onChange).not.toHaveBeenCalled()
  })

  it('applies the native title tooltip', () => {
    render(<ToggleSwitch checked={true} onChange={() => {}} title="Click to disable endpoint" />)
    expect(screen.getByRole('switch')).toHaveAttribute('title', 'Click to disable endpoint')
  })
})
