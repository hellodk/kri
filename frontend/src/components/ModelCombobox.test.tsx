import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, fireEvent, cleanup } from '@testing-library/react'
import { ModelCombobox, AUTO_VALUE, type DiscoveredModel } from './ModelCombobox'

const models: DiscoveredModel[] = [
  { id: 'm1', name: 'llama-3-8b', healthy: true, latency_ms: 12 },
  { id: 'm2', name: 'gpt-oss-20b', healthy: false, latency_ms: null },
]

function setup(value = AUTO_VALUE) {
  const onChange = vi.fn()
  render(
    <ModelCombobox
      models={models}
      value={value}
      onChange={onChange}
      onRefresh={() => {}}
      refreshing={false}
    />,
  )
  // Open the dropdown by clicking the trigger.
  fireEvent.click(screen.getByText('⚡ Auto'))
  return { onChange }
}

afterEach(cleanup)

describe('ModelCombobox', () => {
  it('always renders the Auto option, even when the filter matches no models', () => {
    setup()
    expect(screen.getByText('Auto')).toBeInTheDocument()
    fireEvent.change(screen.getByPlaceholderText('Filter models…'), {
      target: { value: 'zzz-no-match' },
    })
    expect(screen.getByText('Auto')).toBeInTheDocument()
    expect(screen.getByText('No models match')).toBeInTheDocument()
  })

  it('filters the model list by case-insensitive substring', () => {
    setup()
    expect(screen.getByText('llama-3-8b')).toBeInTheDocument()
    expect(screen.getByText('gpt-oss-20b')).toBeInTheDocument()
    fireEvent.change(screen.getByPlaceholderText('Filter models…'), {
      target: { value: 'LLAMA' },
    })
    expect(screen.getByText('llama-3-8b')).toBeInTheDocument()
    expect(screen.queryByText('gpt-oss-20b')).not.toBeInTheDocument()
  })

  it('marks unhealthy models as unreachable and healthy ones as online', () => {
    setup()
    expect(screen.getByText(/unreachable/i)).toBeInTheDocument()
    expect(screen.getByText(/online/i)).toBeInTheDocument()
  })

  it('emits the model id when a model row is selected', () => {
    const { onChange } = setup()
    fireEvent.click(screen.getByText('llama-3-8b'))
    expect(onChange).toHaveBeenCalledWith('m1')
  })

  it('emits AUTO when the Auto option is selected', () => {
    const { onChange } = setup()
    fireEvent.click(screen.getByText('Auto'))
    expect(onChange).toHaveBeenCalledWith(AUTO_VALUE)
  })
})
