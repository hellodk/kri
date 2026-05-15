import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { AuthGuard } from './components/AuthGuard'
import { Layout } from './components/Layout/Layout'
import { LoginPage } from './pages/LoginPage'
import { FleetDashboard } from './pages/FleetDashboard'
import { NodeDetail } from './pages/NodeDetail'
import { DriftExplorer } from './pages/DriftExplorer'
import { SBOMExplorer } from './pages/SBOMExplorer'
import { GroupExplorer } from './pages/GroupExplorer'
import { GroupDetail } from './pages/GroupDetail'
import { ExecutionHistory } from './pages/ExecutionHistory'
import { JobDetail } from './pages/JobDetail'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      retry: 2,
      refetchOnWindowFocus: false,
    },
  },
})

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route
            element={
              <AuthGuard>
                <Layout />
              </AuthGuard>
            }
          >
            <Route index element={<Navigate to="/fleet" replace />} />
            <Route path="/fleet" element={<FleetDashboard />} />
            <Route path="/nodes/:nodeId" element={<NodeDetail />} />
            <Route path="/drift" element={<DriftExplorer />} />
            <Route path="/sbom" element={<SBOMExplorer />} />
            <Route path="/groups" element={<GroupExplorer />} />
            <Route path="/groups/:groupId" element={<GroupDetail />} />
            <Route path="/executions" element={<ExecutionHistory />} />
            <Route path="/executions/:jobId" element={<JobDetail />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  )
}
