import { HubPage } from '../components/HubPage'
import type { HubTab } from '../components/HubPage'
import { ExecutionHistory } from './ExecutionHistory'
import { PlaybooksPage } from './PlaybooksPage'
import { ProvisioningPage } from './ProvisioningPage'
import { SaltOpsPage } from './SaltOpsPage'
import { SaltKeysPage } from './SaltKeysPage'

const TABS: HubTab[] = [
  { key: 'executions',   label: 'Executions',   icon: '▷', component: ExecutionHistory },
  { key: 'playbooks',    label: 'Playbooks',    icon: '▤', component: PlaybooksPage },
  { key: 'provisioning', label: 'Provisioning', icon: '⊡', component: ProvisioningPage },
  { key: 'salt-ops',     label: 'Salt Ops',     icon: '▹', component: SaltOpsPage },
  { key: 'salt-keys',    label: 'Minion Keys',  icon: '⊗', component: SaltKeysPage, showBadge: true },
]

export function AutomationHub() {
  return <HubPage tabs={TABS} defaultTab="executions" />
}
