import { useEffect, useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { HubPage } from '../components/HubPage'
import type { HubTab } from '../components/HubPage'
import { ExecutionHistory } from './ExecutionHistory'
import { PlaybooksPage } from './PlaybooksPage'
import { ProvisioningPage } from './ProvisioningPage'
import { SaltOpsPage } from './SaltOpsPage'
import { SaltKeysPage } from './SaltKeysPage'
import { playbookSourcesApi } from '../api/playbooks'

const TABS: HubTab[] = [
  { key: 'executions',   label: 'Executions',   icon: '▷', component: ExecutionHistory },
  { key: 'playbooks',    label: 'Playbooks',    icon: '▤', component: PlaybooksPage },
  { key: 'provisioning', label: 'Provisioning', icon: '⊡', component: ProvisioningPage },
  { key: 'salt-ops',     label: 'Salt Ops',     icon: '▹', component: SaltOpsPage },
  { key: 'salt-keys',    label: 'Minion Keys',  icon: '⊗', component: SaltKeysPage, showBadge: true },
]

type SyncResult = { label: string; ok: boolean }

export function AutomationHub() {
  const qc = useQueryClient()
  const [syncResults, setSyncResults] = useState<SyncResult[]>([])
  const [bannerVisible, setBannerVisible] = useState(false)
  const hasSynced = useRef(false)

  useEffect(() => {
    // Fire a git pull in the background on every hub mount.
    // By the time the user clicks the Playbooks tab, the pull is done.
    if (hasSynced.current) return
    hasSynced.current = true

    playbookSourcesApi.sync()
      .then((data) => {
        const results: SyncResult[] = (data.results ?? []).map((r: any) => ({
          label: (r.url ?? 'source').split('/').slice(-1)[0].replace('.git', ''),
          ok: r.status === 'ok',
        }))
        if (results.length === 0) return
        setSyncResults(results)
        setBannerVisible(true)
        qc.invalidateQueries({ queryKey: ['playbooks'] })
        setTimeout(() => setBannerVisible(false), 4000)
      })
      .catch(() => { /* silent — sync is best-effort */ })
  }, [qc])

  return (
    <>
      {/* Transient bottom-right toast showing git sync results */}
      <div
        className={`fixed bottom-6 right-6 z-50 transition-all duration-500 ${
          bannerVisible && syncResults.length > 0
            ? 'opacity-100 translate-y-0'
            : 'opacity-0 translate-y-2 pointer-events-none'
        }`}
      >
        <div className="flex items-center gap-3 bg-gray-900 text-white text-xs px-4 py-2.5 rounded-xl shadow-xl">
          <span className="text-gray-400 font-medium">Synced repos:</span>
          {syncResults.map((r, i) => (
            <span key={i} className={`font-semibold ${r.ok ? 'text-green-400' : 'text-red-400'}`}>
              {r.ok ? '✓' : '✗'} {r.label}
            </span>
          ))}
        </div>
      </div>
      <HubPage tabs={TABS} defaultTab="executions" />
    </>
  )
}
