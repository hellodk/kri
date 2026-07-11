import { useState, useRef, useEffect, useCallback } from 'react'
import clsx from 'clsx'
import { Zap } from 'lucide-react'

export const AUTO_VALUE = '__auto__'

export interface DiscoveredModel {
  id: string
  name: string
  healthy: boolean
  latency_ms: number | null
}

interface Props {
  models: DiscoveredModel[]
  value: string
  onChange: (value: string) => void
  onRefresh: () => void
  refreshing: boolean
}

export function ModelCombobox({ models, value, onChange, onRefresh, refreshing }: Props) {
  const [search, setSearch] = useState('')
  const [open, setOpen] = useState(false)
  const containerRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  // close on outside click
  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', handleClick)
    return () => document.removeEventListener('mousedown', handleClick)
  }, [])

  const filtered = models.filter((m) =>
    m.name.toLowerCase().includes(search.toLowerCase())
  )

  const displayValue =
    value === AUTO_VALUE
      ? 'Auto'
      : models.find((m) => m.id === value)?.name ?? value

  function select(id: string) {
    onChange(id)
    setSearch('')
    setOpen(false)
  }

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false)
    },
    []
  )

  const inputClass =
    'w-full px-3 py-2 border border-gray-300 rounded-lg text-sm text-gray-900 ' +
    'focus:outline-hidden focus:border-brand-600 font-mono'

  return (
    <div ref={containerRef} className="relative">
      {/* label row */}
      <div className="flex items-center justify-between mb-1">
        <label className="text-sm font-medium text-gray-700">
          Model <span className="text-red-500">*</span>
        </label>
        <button
          type="button"
          onClick={onRefresh}
          disabled={refreshing}
          className="text-xs text-brand-600 hover:text-brand-700 disabled:opacity-40 flex items-center gap-1"
          title="Re-probe model health"
        >
          <svg
            width="12"
            height="12"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            className={refreshing ? 'animate-spin' : ''}
          >
            <path d="M23 4v6h-6M1 20v-6h6" />
            <path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15" />
          </svg>
          {refreshing ? 'Checking…' : 'Refresh'}
        </button>
      </div>

      {/* trigger input */}
      <div
        className={clsx(
          'w-full px-3 py-2 border rounded-lg text-sm cursor-pointer flex items-center justify-between',
          open ? 'border-brand-600' : 'border-gray-300',
          'bg-white'
        )}
        onClick={() => {
          setOpen((o) => !o)
          setTimeout(() => inputRef.current?.focus(), 0)
        }}
      >
        <span className={clsx('font-mono inline-flex items-center gap-1.5', value === AUTO_VALUE ? 'text-blue-700 font-semibold' : 'text-gray-900')}>
          {value === AUTO_VALUE && <Zap size={14} />}
          {displayValue || <span className="text-gray-400">Select a model…</span>}
        </span>
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#9CA3AF" strokeWidth="2">
          <polyline points="6 9 12 15 18 9" />
        </svg>
      </div>

      {/* dropdown panel */}
      {open && (
        <div className="absolute z-50 w-full mt-1 bg-white border border-gray-200 rounded-lg shadow-lg overflow-hidden">
          {/* search input */}
          <div className="px-3 py-2 border-b border-gray-100">
            <input
              ref={inputRef}
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Filter models…"
              className={inputClass}
              autoComplete="off"
            />
          </div>

          {/* Auto — always pinned, never filtered */}
          <div
            className={clsx(
              'px-3 py-2.5 flex items-center gap-2 cursor-pointer border-b border-blue-100',
              value === AUTO_VALUE ? 'bg-blue-100' : 'bg-blue-50 hover:bg-blue-100'
            )}
            onClick={() => select(AUTO_VALUE)}
          >
            <Zap size={16} className="text-blue-700 shrink-0" />
            <div>
              <div className="text-sm font-semibold text-blue-700">Auto</div>
              <div className="text-xs text-blue-500">Smart router picks best model per request</div>
            </div>
          </div>

          {/* model list */}
          <div className="max-h-52 overflow-y-auto">
            {filtered.length === 0 ? (
              <div className="px-3 py-3 text-xs text-gray-400 text-center">No models match</div>
            ) : (
              filtered.map((m) => (
                <div
                  key={m.id}
                  onClick={() => select(m.id)}
                  className={clsx(
                    'px-3 py-2 flex items-center justify-between border-b border-gray-50 last:border-0',
                    'cursor-pointer hover:bg-gray-50',
                    value === m.id && 'bg-gray-100'
                  )}
                >
                  <span className="font-mono text-sm text-gray-900">{m.name}</span>
                  {m.healthy ? (
                    <span className="text-xs text-green-600 font-medium whitespace-nowrap">
                      ● online{m.latency_ms != null ? ` ${m.latency_ms}ms` : ''}
                    </span>
                  ) : (
                    <span className="text-xs text-amber-600 font-medium whitespace-nowrap">⚠ unreachable</span>
                  )}
                </div>
              ))
            )}
          </div>
        </div>
      )}
    </div>
  )
}
