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
          type="search"
          placeholder="Search nodes… (min 3 chars)"
          onChange={(e) => handleInput(e.target.value)}
          onFocus={() => q.length >= 3 && setOpen(true)}
          onBlur={() => setTimeout(() => setOpen(false), 200)}
          className="w-full px-3 py-1.5 bg-gray-50 border border-gray-300 text-gray-900 placeholder-gray-400 rounded-lg text-sm focus:outline-none focus:border-brand-600 focus:bg-white transition-colors"
        />
        {open && (
          <div className="absolute top-full left-0 right-0 mt-1 bg-white rounded-xl border border-gray-200 shadow-lg overflow-hidden z-50">
            {isLoading ? (
              <div className="px-4 py-3 text-sm text-gray-400">Searching…</div>
            ) : !data || data.items.length === 0 ? (
              <div className="px-4 py-3 text-sm text-gray-400">No nodes found</div>
            ) : (
              data.items.map((r) => (
                <button
                  key={r.id}
                  onClick={() => { navigate(`/nodes/${r.id}`); setOpen(false) }}
                  className="w-full px-4 py-2.5 text-left text-sm hover:bg-gray-50 flex items-center gap-3"
                >
                  <span className="font-medium text-gray-900">{r.hostname ?? r.minion_id}</span>
                  <span className="text-xs text-gray-400">{r.status}</span>
                </button>
              ))
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
