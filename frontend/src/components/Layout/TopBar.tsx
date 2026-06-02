import { useState, useRef, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { searchApi } from '../../api/search'
import { useAuthStore } from '../../stores/authStore'
import { useFilterStore } from '../../stores/filterStore'

export function TopBar() {
  const [q, setQ] = useState('')
  const [open, setOpen] = useState(false)
  const timerRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  const navigate = useNavigate()
  const { clearAuth, user } = useAuthStore()
  const setSidebarOpen = useFilterStore((s) => s.setSidebarOpen)
  const sidebarOpen = useFilterStore((s) => s.sidebarOpen)

  const { data, isLoading } = useQuery({
    queryKey: ['search', q],
    queryFn: () => searchApi.search(q),
    enabled: q.length >= 3,
    staleTime: 5_000,
  })

  useEffect(() => {
    setOpen(q.length >= 3)
  }, [q])

  function handleInput(value: string) {
    clearTimeout(timerRef.current)
    timerRef.current = setTimeout(() => setQ(value), 300)
  }

  async function handleLogout() {
    await clearAuth()
    navigate('/login')
  }

  return (
    <header className="h-14 flex items-center px-4 bg-white border-b border-gray-200 gap-4 shadow-sm">
      <button
        onClick={() => setSidebarOpen(!sidebarOpen)}
        className="text-gray-500 hover:text-gray-700 transition-colors text-lg leading-none"
        aria-label="Toggle sidebar"
      >
        ☰
      </button>
      <div className="relative flex-1 max-w-md">
        <input
          type="text"
          autoComplete="off"
          autoCorrect="off"
          autoCapitalize="off"
          spellCheck={false}
          name="kri-node-search"
          placeholder="Search nodes by hostname or minion ID…"
          onChange={(e) => handleInput(e.target.value)}
          onFocus={() => q.length >= 3 && setOpen(true)}
          onBlur={() => setTimeout(() => setOpen(false), 200)}
          className="w-full px-3 py-1.5 pl-8 bg-gray-50 border border-gray-300 text-gray-900 placeholder-gray-400 rounded-lg text-sm focus:outline-none focus:border-brand-600 focus:bg-white transition-colors"
        />
        <svg className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-gray-400 pointer-events-none" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
        </svg>
        {open && (
          <div className="absolute top-full left-0 right-0 mt-1 bg-white rounded-xl border border-gray-200 shadow-lg overflow-hidden z-50">
            {isLoading ? (
              <div className="px-4 py-3 text-sm text-gray-400 flex items-center gap-2">
                <span className="w-3 h-3 border-2 border-brand-400 border-t-transparent rounded-full animate-spin" />
                Searching…
              </div>
            ) : !data || data.items.length === 0 ? (
              <div className="px-4 py-3 text-sm text-gray-400">No nodes found for <span className="font-mono">"{q}"</span></div>
            ) : (
              <>
                <div className="px-4 py-1.5 bg-gray-50 border-b border-gray-100">
                  <span className="text-xs text-gray-400">{data.items.length} node{data.items.length !== 1 ? 's' : ''} found</span>
                </div>
                {data.items.map((r) => (
                  <button
                    key={r.id}
                    onClick={() => { navigate(`/nodes/${r.id}`); setOpen(false) }}
                    className="w-full px-4 py-2.5 text-left text-sm hover:bg-gray-50 flex items-center gap-3 border-b border-gray-50 last:border-0"
                  >
                    <span className={`w-2 h-2 rounded-full shrink-0 ${
                      r.status === 'online' ? 'bg-green-500' :
                      r.status === 'offline' ? 'bg-red-400' : 'bg-gray-300'
                    }`} />
                    <span className="font-medium text-gray-900 flex-1">{r.hostname ?? r.minion_id}</span>
                    {r.hostname && r.minion_id !== r.hostname && (
                      <span className="text-xs font-mono text-gray-400">{r.minion_id}</span>
                    )}
                    <span className={`text-xs px-1.5 py-0.5 rounded ${
                      r.status === 'online' ? 'bg-green-50 text-green-700' :
                      r.status === 'offline' ? 'bg-red-50 text-red-600' : 'bg-gray-100 text-gray-500'
                    }`}>{r.status}</span>
                  </button>
                ))}
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
