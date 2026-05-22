import { useEffect, useRef } from 'react'
import { BrowserRouter, Routes, Route } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { AuthGuard } from './components/AuthGuard'
import { Layout } from './components/Layout/Layout'
import { LoginPage } from './pages/LoginPage'
import { FleetDashboard } from './pages/FleetDashboard'
import { NodeDetail } from './pages/NodeDetail'
import { DriftExplorer } from './pages/DriftExplorer'
import { DriftComparePage } from './pages/DriftComparePage'
import { SBOMExplorer } from './pages/SBOMExplorer'
import { GroupExplorer } from './pages/GroupExplorer'
import { GroupDetail } from './pages/GroupDetail'
import { ExecutionHistory } from './pages/ExecutionHistory'
import { JobDetail } from './pages/JobDetail'
import { SettingsPage } from './pages/SettingsPage'
import { PlaybooksPage } from './pages/PlaybooksPage'
import { BaselinesPage } from './pages/BaselinesPage'
import { ProvisioningPage } from './pages/ProvisioningPage'
import { SecurityPage } from './pages/SecurityPage'
import { AuditPage } from './pages/AuditPage'
import { SaltKeysPage } from './pages/SaltKeysPage'
import { SaltOpsPage } from './pages/SaltOpsPage'
import { AlertsPage } from './pages/AlertsPage'
import { DashboardPage } from './pages/DashboardPage'
import { saltKeysApi } from './api/saltKeys'
import { useSaltKeysStore } from './stores/saltKeysStore'
import { useToastStore } from './stores/toastStore'
import { useAuthStore } from './stores/authStore'

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
    // setPendingCount and toast are stable Zustand refs — intentionally omitted
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [userId])

  return null
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <SaltKeyWatcher />
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route
            element={
              <AuthGuard>
                <Layout />
              </AuthGuard>
            }
          >
            <Route index element={<DashboardPage />} />
            <Route path="/fleet" element={<FleetDashboard />} />
            <Route path="/nodes/:nodeId" element={<NodeDetail />} />
            <Route path="/drift" element={<DriftExplorer />} />
            <Route path="/drift/compare" element={<DriftComparePage />} />
            <Route path="/sbom" element={<SBOMExplorer />} />
            <Route path="/groups" element={<GroupExplorer />} />
            <Route path="/groups/:groupId" element={<GroupDetail />} />
            <Route path="/executions" element={<ExecutionHistory />} />
            <Route path="/executions/:jobId" element={<JobDetail />} />
            <Route path="/playbooks" element={<PlaybooksPage />} />
            <Route path="/baselines" element={<BaselinesPage />} />
            <Route path="/provisioning" element={<ProvisioningPage />} />
            <Route path="/security" element={<SecurityPage />} />
            <Route path="/audit" element={<AuditPage />} />
            <Route path="/salt-keys" element={<SaltKeysPage />} />
            <Route path="/salt-ops" element={<SaltOpsPage />} />
            <Route path="/alerts" element={<AlertsPage />} />
<Route path="/settings" element={<SettingsPage />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  )
}
