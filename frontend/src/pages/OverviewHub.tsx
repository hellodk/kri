import { LayoutDashboard, Hexagon, HeartPulse, Users, Server } from 'lucide-react'
import { HubPage } from '../components/HubPage'
import type { HubTab } from '../components/HubPage'
import { DashboardPage } from './DashboardPage'
import { FleetDashboard } from './FleetDashboard'
import FleetHealthPage from './FleetHealthPage'
import { MonitoringPage } from './MonitoringPage'
import { GroupExplorer } from './GroupExplorer'
import { SaltMastersTab } from './SaltMastersTab'

function FleetHealthAndMonitoring() {
  return (
    <div className="space-y-6">
      <FleetHealthPage />
      <MonitoringPage />
    </div>
  )
}

const TABS: HubTab[] = [
  { key: 'fleet-overview', label: 'Fleet Overview', icon: LayoutDashboard, component: DashboardPage },
  { key: 'fleet',          label: 'Fleet',          icon: Hexagon,         component: FleetDashboard },
  { key: 'fleet-health',   label: 'Fleet Health',   icon: HeartPulse,      component: FleetHealthAndMonitoring },
  { key: 'groups',         label: 'Groups',         icon: Users,           component: GroupExplorer },
  { key: 'salt-masters',   label: 'Salt Masters',   icon: Server,          component: SaltMastersTab },
]

export function OverviewHub() {
  return <HubPage tabs={TABS} defaultTab="fleet-overview" />
}
