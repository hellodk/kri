import { HubPage } from '../components/HubPage'
import type { HubTab } from '../components/HubPage'
import { DriftExplorer } from './DriftExplorer'
import { BaselinesPage } from './BaselinesPage'
import { SBOMExplorer } from './SBOMExplorer'
import { LicensePage } from './LicensePage'
import { SecurityPage } from './SecurityPage'
import { AlertsPage } from './AlertsPage'

const TABS: HubTab[] = [
  { key: 'drift',     label: 'Drift',     icon: '◑', component: DriftExplorer },
  { key: 'baselines', label: 'Baselines', icon: '▬', component: BaselinesPage },
  { key: 'sbom',      label: 'SBOM',      icon: '◉', component: SBOMExplorer },
  { key: 'licenses',  label: 'Licenses',  icon: '⚖', component: LicensePage },
  { key: 'security',  label: 'Security',  icon: '⛨', component: SecurityPage },
  { key: 'alerts',    label: 'Alerts',    icon: '◭', component: AlertsPage },
]

export function ComplianceHub() {
  return <HubPage tabs={TABS} defaultTab="drift" />
}
