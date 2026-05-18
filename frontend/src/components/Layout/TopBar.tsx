import { useState, useRef } from 'react'
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

  const { data } = useQuery({
    queryKey: ['search', q],
    queryFn: () => searchApi.search(q),
    enabled: q.length >= 3,
    staleTime: 5_000,
  })

  function handleInput(value: string) {
    clearTimeout(timerRef.current)
    timerRef.current = setTimeout(() => setQ(value), 300)
    setOpen(value.length >= 3)
  }

  async function handleLogout() {
    await clearAuth()
    navigate('/login')
  }

  return (
    <header className="h-14 flex items-center px-4 bg-gray-900/80 backdrop-blur border-b border-white/10 gap-4">
      <button
        onClick={() => setSidebarOpen(!sidebarOpen)}
        className="text-white/40 hover:text-white/80 transition-colors text-lg leading-none"
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
          className="w-full px-3 py-1.5 bg-white/5 border border-white/10 text-white placeholder-white/25 rounded-lg text-sm focus:outline-none focus:border-brand-500 focus:bg-white/8 transition-colors"
        />
        {open && data && data.items.length > 0 && (
          <ul className="absolute top-full mt-1 w-full rounded-lg shadow-xl z-50 max-h-60 overflow-auto border border-white/10"
              style={{ background: '#1a1a3e' }}>
            {data.items.map((r) => (
              <li key={r.id}>
                <button
                  className="w-full text-left px-3 py-2.5 text-sm hover:bg-white/5 transition-colors"
                  onClick={() => { navigate(`/nodes/${r.id}`); setOpen(false) }}
                >
                  <span className="font-medium text-white">{r.hostname ?? r.minion_id}</span>
                  <span className="ml-2 text-white/30 text-xs">{r.status}</span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
      <div className="ml-auto flex items-center gap-3 text-sm">
        <span className="text-white/50">{user?.email}</span>
        <span className="text-xs text-white/30 bg-white/5 border border-white/10 px-2 py-0.5 rounded-full font-mono">{user?.role}</span>
        <button onClick={handleLogout} className="text-white/30 hover:text-red-400 transition-colors text-sm">
          Sign out
        </button>
      </div>
    </header>
  )
}
