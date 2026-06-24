import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, fireEvent, cleanup } from '@testing-library/react'
import { useFocusTrap } from './useFocusTrap'

function Modal({ onClose }: { onClose?: () => void }) {
  const ref = useFocusTrap<HTMLDivElement>(true, onClose)
  return (
    <div ref={ref} role="dialog">
      <button>first</button>
      <button>middle</button>
      <button>last</button>
    </div>
  )
}

afterEach(cleanup)

describe('useFocusTrap', () => {
  it('focuses the first focusable element when activated', () => {
    render(<Modal />)
    expect(screen.getByText('first')).toHaveFocus()
  })

  it('wraps Tab from the last element back to the first', () => {
    render(<Modal />)
    const last = screen.getByText('last')
    last.focus()
    fireEvent.keyDown(document, { key: 'Tab' })
    expect(screen.getByText('first')).toHaveFocus()
  })

  it('wraps Shift+Tab from the first element to the last', () => {
    render(<Modal />)
    const first = screen.getByText('first')
    first.focus()
    fireEvent.keyDown(document, { key: 'Tab', shiftKey: true })
    expect(screen.getByText('last')).toHaveFocus()
  })

  it('calls onClose on Escape', () => {
    const onClose = vi.fn()
    render(<Modal onClose={onClose} />)
    fireEvent.keyDown(document, { key: 'Escape' })
    expect(onClose).toHaveBeenCalledOnce()
  })
})
