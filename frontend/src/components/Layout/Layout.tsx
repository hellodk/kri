import { Suspense } from 'react'
import { Link } from 'react-router-dom'
import { Outlet } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { ErrorBoundary } from '../ErrorBoundary'
import { Sidebar } from './Sidebar'
import { TopBar } from './TopBar'
import { ToastContainer } from '../ToastContainer'
import { saltMastersApi } from '../../api/saltMasters'
import { fleetActionsBlocked } from '../../lib/saltMasterGuard'

function RouteSpinner() {
  return (
    <div className="flex items-center justify-center py-16" role="status" aria-live="polite">
      <span className="inline-block h-6 w-6 rounded-full border-2 border-gray-300 border-t-brand-600 animate-spin" />
      <span className="sr-only">Loading…</span>
    </div>
  )
}

function NoMasterBanner() {
  const { data: masters } = useQuery({
    queryKey: ['salt-masters'],
    queryFn: saltMastersApi.list,
    staleTime: 60_000,
    refetchInterval: 120_000,
  })

  if (!fleetActionsBlocked(masters)) return null

  return (
    <div
      role="alert"
      aria-live="polite"
      style={{
        background: '#92400E',
        borderBottom: '2px solid #78350F',
      }}
      className="flex items-center justify-between gap-3 px-4 py-2.5"
    >
      <div className="flex items-center gap-2.5 min-w-0">
        <svg
          width="18"
          height="18"
          viewBox="0 0 20 20"
          fill="none"
          aria-hidden="true"
          className="flex-shrink-0"
        >
          <path
            d="M10 2a8 8 0 100 16A8 8 0 0010 2zm0 4a.75.75 0 01.75.75v3.5a.75.75 0 01-1.5 0v-3.5A.75.75 0 0110 6zm0 7a1 1 0 110 2 1 1 0 010-2z"
            fill="#FDE68A"
          />
        </svg>
        <span className="text-sm font-semibold" style={{ color: '#FDE68A' }}>
          No salt-master configured —
        </span>
        <span className="text-sm" style={{ color: '#FEF3C7' }}>
          fleet actions are disabled until you add and enable one.
        </span>
      </div>
      <Link
        to="/settings?tab=Salt Masters"
        className="flex-shrink-0 px-3 py-1 text-xs font-semibold rounded-md border transition-colors"
        style={{
          background: '#FEF3C7',
          color: '#78350F',
          borderColor: '#FDE68A',
        }}
        onMouseEnter={(e) => {
          ;(e.currentTarget as HTMLAnchorElement).style.background = '#FDE68A'
        }}
        onMouseLeave={(e) => {
          ;(e.currentTarget as HTMLAnchorElement).style.background = '#FEF3C7'
        }}
      >
        Settings → Salt Masters
      </Link>
    </div>
  )
}

export function Layout() {
  return (
    <div className="flex h-screen overflow-hidden" style={{ background: '#F9FAFB' }}>
      <Sidebar />
      <div className="flex-1 flex flex-col overflow-hidden">
        <TopBar />
        <NoMasterBanner />
        <main className="flex-1 overflow-auto p-6" style={{ background: '#F9FAFB' }}>
          {/* Route-level Suspense boundary for the lazy-loaded pages
              imported in App.tsx. The fallback is intentionally minimal so
              switching tabs doesn't flash a layout-breaking placeholder. */}
          <ErrorBoundary>
            <Suspense fallback={<RouteSpinner />}>
              <Outlet />
            </Suspense>
          </ErrorBoundary>
        </main>
      </div>
      <ToastContainer />
    </div>
  )
}
