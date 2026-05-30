import { HubPage } from '../components/HubPage'
import type { HubTab } from '../components/HubPage'
import { DashboardPage } from './DashboardPage'
import { FleetDashboard } from './FleetDashboard'
import FleetHealthPage from './FleetHealthPage'
import { MonitoringPage } from './MonitoringPage'
import { GroupExplorer } from './GroupExplorer'

function FleetHealthAndMonitoring() {
  return (
    <div className="space-y-6">
      <FleetHealthPage />
      <MonitoringPage />
    </div>
  )
}

const TABS: HubTab[] = [
  { key: 'fleet-overview', label: 'Fleet Overview', icon: '⊞', component: DashboardPage },
  { key: 'fleet',          label: 'Fleet',          icon: '⬡', component: FleetDashboard },
  { key: 'fleet-health',   label: 'Fleet Health',   icon: '♥', component: FleetHealthAndMonitoring },
  { key: 'groups',         label: 'Groups',         icon: '◫', component: GroupExplorer },
]

export function OverviewHub() {
  return <HubPage tabs={TABS} defaultTab="fleet-overview" />
}
