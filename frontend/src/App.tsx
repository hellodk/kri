import { lazy, useEffect, useRef, useState } from 'react'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { AuthGuard } from './components/AuthGuard'
import { ErrorBoundary } from './components/ErrorBoundary'
import { Layout } from './components/Layout/Layout'
import { LoginPage } from './pages/LoginPage'
import { OidcCallbackPage } from './pages/OidcCallbackPage'
// Eager-load the four hub pages — they're the AuthGuard landing surfaces
// (`/overview`, `/compliance`, `/automation`, `/fleet`) that operators hit
// on every login. Splitting them out forces a flash-of-spinner that hurts
// perceived performance more than it helps the bundle.
import { FleetDashboard } from './pages/FleetDashboard'
import { OverviewHub } from './pages/OverviewHub'
import { ComplianceHub } from './pages/ComplianceHub'
import { AutomationHub } from './pages/AutomationHub'
import { saltKeysApi } from './api/saltKeys'
import { useSaltKeysStore } from './stores/saltKeysStore'
import { useToastStore } from './stores/toastStore'
import { useAuthStore } from './stores/authStore'
import LLMAssistant from './components/LLMAssistant'
import { useKeyboardShortcuts } from './hooks/useKeyboardShortcuts'
import { KeyboardShortcutsOverlay } from './components/KeyboardShortcutsOverlay'

// Everything below is route-level lazy-loaded. NodeDetail (2347 LOC) and
// BaselinesPage (~700 LOC) alone account for ~30% of the bundle and only
// load on operator-driven navigation, so deferring them is a clear win
// (#arch-nodedetail). The default-export shim lets us keep the named
// exports unchanged in the source files; FleetHealthPage already exports
// default and needs no shim.
const NodeDetail = lazy(() => import('./pages/NodeDetail').then((m) => ({ default: m.NodeDetail })))
const DriftExplorer = lazy(() => import('./pages/DriftExplorer').then((m) => ({ default: m.DriftExplorer })))
const DriftComparePage = lazy(() => import('./pages/DriftComparePage').then((m) => ({ default: m.DriftComparePage })))
const SBOMExplorer = lazy(() => import('./pages/SBOMExplorer').then((m) => ({ default: m.SBOMExplorer })))
const LicensePage = lazy(() => import('./pages/LicensePage').then((m) => ({ default: m.LicensePage })))
const GroupExplorer = lazy(() => import('./pages/GroupExplorer').then((m) => ({ default: m.GroupExplorer })))
const GroupDetail = lazy(() => import('./pages/GroupDetail').then((m) => ({ default: m.GroupDetail })))
const ExecutionHistory = lazy(() => import('./pages/ExecutionHistory').then((m) => ({ default: m.ExecutionHistory })))
const JobDetail = lazy(() => import('./pages/JobDetail').then((m) => ({ default: m.JobDetail })))
const PlaybookJobDetail = lazy(() => import('./pages/PlaybookJobDetail').then((m) => ({ default: m.PlaybookJobDetail })))
const SettingsPage = lazy(() => import('./pages/SettingsPage').then((m) => ({ default: m.SettingsPage })))
const PlaybooksPage = lazy(() => import('./pages/PlaybooksPage').then((m) => ({ default: m.PlaybooksPage })))
const BaselinesPage = lazy(() => import('./pages/BaselinesPage').then((m) => ({ default: m.BaselinesPage })))
const ProvisioningPage = lazy(() => import('./pages/ProvisioningPage').then((m) => ({ default: m.ProvisioningPage })))
const SecurityPage = lazy(() => import('./pages/SecurityPage').then((m) => ({ default: m.SecurityPage })))
const AuditPage = lazy(() => import('./pages/AuditPage').then((m) => ({ default: m.AuditPage })))
const SaltKeysPage = lazy(() => import('./pages/SaltKeysPage').then((m) => ({ default: m.SaltKeysPage })))
const SaltOpsPage = lazy(() => import('./pages/SaltOpsPage').then((m) => ({ default: m.SaltOpsPage })))
const AlertsPage = lazy(() => import('./pages/AlertsPage').then((m) => ({ default: m.AlertsPage })))
const FleetHealthPage = lazy(() => import('./pages/FleetHealthPage'))
const DashboardPage = lazy(() => import('./pages/DashboardPage').then((m) => ({ default: m.DashboardPage })))
const MonitoringPage = lazy(() => import('./pages/MonitoringPage').then((m) => ({ default: m.MonitoringPage })))

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      retry: 2,
      refetchOnWindowFocus: false,
    },
  },
})

// Polls for pending salt keys and updates the notification store.
function SaltKeyWatcher() {
  const setPendingCount = useSaltKeysStore((s) => s.setPendingCount)
  const toast = useToastStore((s) => s.add)
  // Use a stable primitive (id string) not the whole user object —
  // persist middleware creates a new object reference on every render.
  const userId = useAuthStore((s) => s.user?.id as string | undefined)
  const prevCount = useRef(0)

  useEffect(() => {
    if (!userId) return

    async function poll() {
      if (!localStorage.getItem('access_token')) return
      try {
        const keys = await saltKeysApi.list()
        const n = keys.pending_count
        if (n > prevCount.current) {
          toast(`${n - prevCount.current} new minion key${n - prevCount.current > 1 ? 's' : ''} pending approval`, 'info')
        }
        prevCount.current = n
        setPendingCount(n)
      } catch {
        // silently ignore — user may not be authenticated yet
      }
    }

    poll()
    const id = setInterval(poll, 30_000)
    return () => clearInterval(id)
  }, [userId, setPendingCount, toast])

  return null
}

function NotFoundPage() {
  return (
    <div className="flex flex-col items-center justify-center h-full min-h-[60vh] gap-4 text-center px-4">
      <span className="text-6xl font-mono text-gray-300">404</span>
      <h1 className="text-xl font-semibold text-gray-700">Page not found</h1>
      <p className="text-sm text-gray-500 max-w-sm">
        The page you're looking for doesn't exist or has been moved.
      </p>
      <a href="/fleet" className="mt-2 px-4 py-2 rounded-lg bg-brand-600 text-white text-sm font-medium hover:bg-brand-700 transition-colors">
        Back to Fleet
      </a>
    </div>
  )
}

export default function App() {
  const [shortcutsOpen, setShortcutsOpen] = useState(false)

  useKeyboardShortcuts({
    '?': () => setShortcutsOpen((v) => !v),
    'ctrl+k': () => {
      const input = document.querySelector<HTMLInputElement>(
        'input[type="search"], input[placeholder*="search" i], input[placeholder*="filter" i]'
      )
      input?.focus()
    },
    '/': () => {
      const input = document.querySelector<HTMLInputElement>(
        'input[type="search"], input[placeholder*="search" i], input[placeholder*="filter" i]'
      )
      input?.focus()
    },
  })

  return (
    <ErrorBoundary>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <SaltKeyWatcher />
        <KeyboardShortcutsOverlay open={shortcutsOpen} onClose={() => setShortcutsOpen(false)} />
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/auth/callback" element={<OidcCallbackPage />} />
          <Route
            element={
              <AuthGuard>
                <>
                  <Layout />
                  <LLMAssistant />
                </>
              </AuthGuard>
            }
          >
            {/* All non-hub routes resolve through React.lazy(); a single
                Suspense boundary at this level shows the spinner during
                code-split chunk load (#arch-nodedetail). */}
            <Route index element={<Navigate to="/overview" replace />} />
            <Route path="/overview" element={<OverviewHub />} />
            <Route path="/compliance" element={<ComplianceHub />} />
            <Route path="/automation" element={<AutomationHub />} />
            <Route path="/fleet" element={<FleetDashboard />} />
            <Route path="/nodes/:nodeId" element={<NodeDetail />} />
            <Route path="/drift" element={<DriftExplorer />} />
            <Route path="/drift/compare" element={<DriftComparePage />} />
            <Route path="/sbom" element={<SBOMExplorer />} />
            <Route path="/licenses" element={<LicensePage />} />
            <Route path="/groups" element={<GroupExplorer />} />
            <Route path="/groups/:groupId" element={<GroupDetail />} />
            <Route path="/executions" element={<ExecutionHistory />} />
            <Route path="/executions/:jobId" element={<JobDetail />} />
            <Route path="/playbook-job/:jobId" element={<PlaybookJobDetail />} />
            <Route path="/playbooks" element={<PlaybooksPage />} />
            <Route path="/baselines" element={<BaselinesPage />} />
            <Route path="/provisioning" element={<ProvisioningPage />} />
            <Route path="/security" element={<SecurityPage />} />
            <Route path="/audit" element={<AuditPage />} />
            <Route path="/salt-keys" element={<SaltKeysPage />} />
            <Route path="/salt-ops" element={<SaltOpsPage />} />
            <Route path="/alerts" element={<AlertsPage />} />
            <Route path="/fleet-health" element={<FleetHealthPage />} />
            <Route path="/monitoring" element={<MonitoringPage />} />
            <Route path="/dashboard" element={<DashboardPage />} />
            <Route path="/settings" element={<SettingsPage />} />
            <Route path="*" element={<NotFoundPage />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
    </ErrorBoundary>
  )
}
