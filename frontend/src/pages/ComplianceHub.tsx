import { GitCompare, Layers, Package, Scale, ShieldCheck, Bell, Settings } from 'lucide-react'
import { HubPage } from '../components/HubPage'
import type { HubTab } from '../components/HubPage'
import { DriftExplorer } from './DriftExplorer'
import { BaselinesPage } from './BaselinesPage'
import { SBOMExplorer } from './SBOMExplorer'
import { LicensePage } from './LicensePage'
import { SecurityPage } from './SecurityPage'
import { AlertsPage } from './AlertsPage'
import { MobileconfigManager } from './MobileconfigManager'

const TABS: HubTab[] = [
  { key: 'drift',     label: 'Drift',           icon: GitCompare,  component: DriftExplorer },
  { key: 'baselines', label: 'Baselines',        icon: Layers,      component: BaselinesPage },
  { key: 'sbom',      label: 'SBOM',             icon: Package,     component: SBOMExplorer },
  { key: 'licenses',  label: 'Licenses',         icon: Scale,       component: LicensePage },
  { key: 'security',  label: 'Security',         icon: ShieldCheck, component: SecurityPage },
  { key: 'alerts',    label: 'Alerts',           icon: Bell,        component: AlertsPage },
  { key: 'profiles',  label: 'Config Profiles',  icon: Settings,    component: MobileconfigManager },
]

export function ComplianceHub() {
  return <HubPage tabs={TABS} defaultTab="drift" />
}
