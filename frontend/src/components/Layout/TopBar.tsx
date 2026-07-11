import { useState, useRef, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { Monitor, Users, Play, Hexagon, Sparkles, type LucideIcon } from 'lucide-react'
import { api } from '../../api/client'
import { useAuthStore } from '../../stores/authStore'
import { useFilterStore } from '../../stores/filterStore'

interface SearchResult {
  type: 'node' | 'group' | 'ansible_job' | 'salt_execution' | 'llm_query'
  id: string
  title: string
  subtitle: string
  status?: string
  url: string
  score: number
}

interface SearchResponse {
  query: string
  is_uuid_search: boolean
  results: SearchResult[]
  total: number
}

const TYPE_LABEL: Record<string, string> = {
  node: 'Nodes',
  group: 'Groups',
  ansible_job: 'Playbook Runs',
  salt_execution: 'Salt Executions',
  llm_query: 'AI Queries',
}

const TYPE_ICON: Record<string, LucideIcon> = {
  node: Monitor,
  group: Users,
  ansible_job: Play,
  salt_execution: Hexagon,
  llm_query: Sparkles,
}

function statusDot(status?: string) {
  if (!status) return null
  const colour =
    status === 'online' || status === 'completed' ? 'bg-green-500' :
    status === 'offline' || status === 'failed' ? 'bg-red-400' :
    status === 'running' ? 'bg-blue-400 animate-pulse' :
    'bg-gray-300'
  return <span className={`w-1.5 h-1.5 rounded-full shrink-0 inline-block ${colour}`} />
}

export function TopBar() {
  const [q, setQ] = useState('')
  const [inputVal, setInputVal] = useState('')
  const [open, setOpen] = useState(false)
  const [selectedIdx, setSelectedIdx] = useState(-1)
  const timerRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  const inputRef = useRef<HTMLInputElement>(null)
  const navigate = useNavigate()
  const { clearAuth, user } = useAuthStore()
  const setSidebarOpen = useFilterStore((s) => s.setSidebarOpen)
  const sidebarOpen = useFilterStore((s) => s.sidebarOpen)

  const { data, isLoading } = useQuery({
    queryKey: ['search', q],
    queryFn: () => api.get<SearchResponse>(`/api/v1/search?q=${encodeURIComponent(q)}`),
    enabled: q.length >= 2,
    staleTime: 5_000,
  })

  const results: SearchResult[] = data?.results ?? []

  // Group results by type for display
  const grouped = results.reduce<Record<string, SearchResult[]>>((acc, r) => {
    if (!acc[r.type]) acc[r.type] = []
    acc[r.type].push(r)
    return acc
  }, {})

  // Flat list for keyboard navigation
  const flat = results
  const resultIndexMap = new Map(results.map((r, i) => [r, i]))

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- syncing dropdown open state from query string length; refactor tracked in #380 follow-up
    setOpen(q.length >= 2)
    setSelectedIdx(-1)
  }, [q])

  // Cmd+K / Ctrl+K global shortcut
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault()
        inputRef.current?.focus()
        inputRef.current?.select()
        setOpen(true)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  function handleInput(value: string) {
    setInputVal(value)
    clearTimeout(timerRef.current)
    timerRef.current = setTimeout(() => setQ(value), 250)
  }

  function handleKeyDown(e: React.KeyboardEvent) {
    if (e.key === 'ArrowDown') { e.preventDefault(); setSelectedIdx(i => Math.min(i + 1, flat.length - 1)) }
    if (e.key === 'ArrowUp') { e.preventDefault(); setSelectedIdx(i => Math.max(i - 1, -1)) }
    if (e.key === 'Enter' && selectedIdx >= 0 && flat[selectedIdx]) {
      navigate(flat[selectedIdx].url)
      setOpen(false)
      setInputVal('')
      setQ('')
    }
    if (e.key === 'Escape') { setOpen(false); inputRef.current?.blur() }
  }

  async function handleLogout() {
    await clearAuth()
    navigate('/login')
  }

  return (
    <header className="h-14 flex items-center px-4 bg-white border-b border-gray-200 gap-4 shadow-xs">
      <button
        onClick={() => setSidebarOpen(!sidebarOpen)}
        className="text-gray-500 hover:text-gray-700 transition-colors text-lg leading-none"
        aria-label="Toggle sidebar"
      >
        ☰
      </button>

      <div className="relative flex-1 max-w-lg">
        <input
          ref={inputRef}
          type="text"
          autoComplete="off"
          autoCorrect="off"
          autoCapitalize="off"
          spellCheck={false}
          name="kri-unified-search"
          value={inputVal}
          placeholder="Search nodes, groups, jobs, IDs… (⌘K)"
          onChange={(e) => handleInput(e.target.value)}
          onFocus={() => q.length >= 2 && setOpen(true)}
          onBlur={() => setTimeout(() => setOpen(false), 150)}
          onKeyDown={handleKeyDown}
          className="w-full px-3 py-1.5 pl-8 bg-gray-50 border border-gray-300 text-gray-900 placeholder-gray-400 rounded-lg text-sm focus:outline-hidden focus:border-brand-600 focus:bg-white transition-colors"
        />
        <svg className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-gray-400 pointer-events-none" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
        </svg>

        {open && (
          <div className="absolute top-full left-0 right-0 mt-1 bg-white rounded-xl border border-gray-200 shadow-xl overflow-hidden z-50 max-h-[70vh] overflow-y-auto">
            {isLoading ? (
              <div className="px-4 py-3 text-sm text-gray-400 flex items-center gap-2">
                <span className="w-3 h-3 border-2 border-brand-400 border-t-transparent rounded-full animate-spin" />
                Searching…
              </div>
            ) : results.length === 0 ? (
              <div className="px-4 py-4 text-sm text-gray-400 text-center">
                {data?.is_uuid_search
                  ? `No execution found with ID starting "${q}"`
                  : `No results for "${q}"`}
              </div>
            ) : (
              <>
                {data?.is_uuid_search && (
                  <div className="px-4 py-1.5 bg-blue-50 border-b border-blue-100 text-xs text-blue-600">
                    UUID prefix search — showing matching executions
                  </div>
                )}
                {Object.entries(grouped).map(([type, items]) => {
                  return (
                    <div key={type}>
                      <div className="px-4 py-1 bg-gray-50 border-b border-gray-100">
                        <span className="text-xs font-semibold text-gray-400 uppercase tracking-wide inline-flex items-center gap-1.5">
                          {(() => {
                            const Icon = TYPE_ICON[type]
                            return Icon ? <Icon size={12} /> : null
                          })()}
                          {TYPE_LABEL[type] ?? type}
                        </span>
                      </div>
                      {items.map((r) => {
                        const globalIdx = resultIndexMap.get(r) ?? -1
                        return (
                          <button
                            key={r.id}
                            onMouseDown={() => { navigate(r.url); setOpen(false); setInputVal(''); setQ('') }}
                            className={`w-full px-4 py-2.5 text-left text-sm flex items-center gap-2.5 border-b border-gray-50 last:border-0 ${
                              globalIdx === selectedIdx ? 'bg-brand-50' : 'hover:bg-gray-50'
                            }`}
                          >
                            {statusDot(r.status)}
                            <div className="flex-1 min-w-0">
                              <span className="font-medium text-gray-900 block truncate">{r.title}</span>
                              <span className="text-xs text-gray-400 block truncate">{r.subtitle}</span>
                            </div>
                            {globalIdx === selectedIdx && (
                              <span className="text-xs text-gray-300 shrink-0">↵</span>
                            )}
                          </button>
                        )
                      })}
                    </div>
                  )
                })}
                <div className="px-4 py-1.5 bg-gray-50 border-t border-gray-100 flex items-center gap-3 text-xs text-gray-400">
                  <span>{results.length} result{results.length !== 1 ? 's' : ''}</span>
                  <span>↑↓ navigate</span>
                  <span>↵ open</span>
                  <span>esc close</span>
                </div>
              </>
            )}
          </div>
        )}
      </div>

      <div className="ml-auto flex items-center gap-3 text-sm">
        <span className="text-gray-700 font-medium">{user?.email}</span>
        <span className="text-xs text-gray-500 bg-gray-100 border border-gray-200 px-2 py-0.5 rounded-full">{user?.role}</span>
        <button onClick={handleLogout} className="text-gray-500 hover:text-red-600 transition-colors font-medium">
          Sign out
        </button>
      </div>
    </header>
  )
}
