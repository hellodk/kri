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
        {open && data && data.items.length > 0 && (
          <ul className="absolute top-full mt-1 w-full bg-white border border-gray-200 rounded-lg shadow-lg z-50 max-h-60 overflow-auto">
            {data.items.map((r) => (
              <li key={r.id}>
                <button
                  className="w-full text-left px-3 py-2.5 text-sm text-gray-900 hover:bg-gray-50 transition-colors"
                  onClick={() => { navigate(`/nodes/${r.id}`); setOpen(false) }}
                >
                  <span className="font-medium">{r.hostname ?? r.minion_id}</span>
                  <span className="ml-2 text-gray-400 text-xs">{r.status}</span>
                </button>
              </li>
            ))}
          </ul>
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
