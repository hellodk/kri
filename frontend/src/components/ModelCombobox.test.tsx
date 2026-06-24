import { useState } from 'react'
import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, fireEvent, cleanup } from '@testing-library/react'
import { ModelCombobox, AUTO_VALUE, type DiscoveredModel } from './ModelCombobox'

const models: DiscoveredModel[] = [
  { id: 'm1', name: 'llama-3-8b', healthy: true, latency_ms: 12 },
  { id: 'm2', name: 'gpt-oss-20b', healthy: false, latency_ms: null },
]

function setup(value = AUTO_VALUE, onRefresh = () => {}, refreshing = false) {
  const onChange = vi.fn()
  render(
    <ModelCombobox
      models={models}
      value={value}
      onChange={onChange}
      onRefresh={onRefresh}
      refreshing={refreshing}
    />,
  )
  // Open the dropdown by clicking the trigger.
  const triggerText = value === AUTO_VALUE ? '⚡ Auto' : models.find(m => m.id === value)?.name ?? value
  fireEvent.click(screen.getByText(triggerText))
  return { onChange }
}

// A controlled wrapper so we can test model-switching end-to-end.
function ControlledCombobox({ initial = AUTO_VALUE }: { initial?: string }) {
  const [value, setValue] = useState(initial)
  return (
    <ModelCombobox
      models={models}
      value={value}
      onChange={setValue}
      onRefresh={() => {}}
      refreshing={false}
    />
  )
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

  it('trigger shows the selected model name when a specific model is pre-selected', () => {
    // When the value is a model id the trigger must display the model name,
    // not "Auto".
    render(
      <ModelCombobox
        models={models}
        value="m1"
        onChange={() => {}}
        onRefresh={() => {}}
        refreshing={false}
      />,
    )
    expect(screen.getByText('llama-3-8b')).toBeInTheDocument()
    expect(screen.queryByText('⚡ Auto')).not.toBeInTheDocument()
  })

  it('displays latency for healthy models', () => {
    setup()
    // llama-3-8b is healthy with latency_ms: 12
    expect(screen.getByText(/12ms/)).toBeInTheDocument()
  })

  it('closes the dropdown when Escape is pressed', () => {
    setup()
    // Dropdown is open — the filter input is visible
    expect(screen.getByPlaceholderText('Filter models…')).toBeInTheDocument()
    fireEvent.keyDown(screen.getByPlaceholderText('Filter models…'), { key: 'Escape' })
    expect(screen.queryByPlaceholderText('Filter models…')).not.toBeInTheDocument()
  })

  it('calls onRefresh when the refresh button is clicked', () => {
    const onRefresh = vi.fn()
    render(
      <ModelCombobox
        models={models}
        value={AUTO_VALUE}
        onChange={() => {}}
        onRefresh={onRefresh}
        refreshing={false}
      />,
    )
    fireEvent.click(screen.getByTitle('Re-probe model health'))
    expect(onRefresh).toHaveBeenCalledOnce()
  })

  it('shows "Checking…" and disables the refresh button while refreshing', () => {
    render(
      <ModelCombobox
        models={models}
        value={AUTO_VALUE}
        onChange={() => {}}
        onRefresh={() => {}}
        refreshing={true}
      />,
    )
    expect(screen.getByText('Checking…')).toBeInTheDocument()
    expect(screen.getByTitle('Re-probe model health')).toBeDisabled()
  })

  it('dropdown closes after a model is selected', () => {
    setup()
    expect(screen.getByPlaceholderText('Filter models…')).toBeInTheDocument()
    fireEvent.click(screen.getByText('llama-3-8b'))
    expect(screen.queryByPlaceholderText('Filter models…')).not.toBeInTheDocument()
  })

  it('switches between two models correctly (controlled integration)', () => {
    render(<ControlledCombobox initial="m1" />)

    // Trigger shows m1 initially
    expect(screen.getByText('llama-3-8b')).toBeInTheDocument()

    // Open dropdown and switch to m2
    fireEvent.click(screen.getByText('llama-3-8b'))
    fireEvent.click(screen.getByText('gpt-oss-20b'))

    // Trigger now shows m2
    expect(screen.getByText('gpt-oss-20b')).toBeInTheDocument()
    expect(screen.queryByText('⚡ Auto')).not.toBeInTheDocument()
  })

  it('switches from a specific model back to Auto (controlled integration)', () => {
    render(<ControlledCombobox initial="m1" />)

    fireEvent.click(screen.getByText('llama-3-8b'))
    // "Auto" appears twice: once in the pinned row header and once in the trigger
    // after selection. Before selection we click the dropdown row labelled "Auto".
    fireEvent.click(screen.getAllByText('Auto')[0])

    expect(screen.getByText('⚡ Auto')).toBeInTheDocument()
  })
})
