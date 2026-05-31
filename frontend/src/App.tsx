import { useEffect, useRef, useState } from 'react'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { AuthGuard } from './components/AuthGuard'
import { Layout } from './components/Layout/Layout'
import { LoginPage } from './pages/LoginPage'
import { OidcCallbackPage } from './pages/OidcCallbackPage'
import { FleetDashboard } from './pages/FleetDashboard'
import { NodeDetail } from './pages/NodeDetail'
import { DriftExplorer } from './pages/DriftExplorer'
import { DriftComparePage } from './pages/DriftComparePage'
import { SBOMExplorer } from './pages/SBOMExplorer'
import { LicensePage } from './pages/LicensePage'
import { GroupExplorer } from './pages/GroupExplorer'
import { GroupDetail } from './pages/GroupDetail'
import { ExecutionHistory } from './pages/ExecutionHistory'
import { JobDetail } from './pages/JobDetail'
import { PlaybookJobDetail } from './pages/PlaybookJobDetail'
import { SettingsPage } from './pages/SettingsPage'
import { PlaybooksPage } from './pages/PlaybooksPage'
import { BaselinesPage } from './pages/BaselinesPage'
import { ProvisioningPage } from './pages/ProvisioningPage'
import { SecurityPage } from './pages/SecurityPage'
import { AuditPage } from './pages/AuditPage'
import { SaltKeysPage } from './pages/SaltKeysPage'
import { SaltOpsPage } from './pages/SaltOpsPage'
import { AlertsPage } from './pages/AlertsPage'
import FleetHealthPage from './pages/FleetHealthPage'
import { DashboardPage } from './pages/DashboardPage'
import { MonitoringPage } from './pages/MonitoringPage'
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
  )
}
