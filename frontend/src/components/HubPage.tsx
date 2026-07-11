import { useSearchParams } from 'react-router-dom'
import type { LucideIcon } from 'lucide-react'
import { useSaltKeysStore } from '../stores/saltKeysStore'

export interface HubTab {
  key: string
  label: string
  icon: LucideIcon
  component: React.ComponentType
  showBadge?: boolean
}

interface HubPageProps {
  tabs: HubTab[]
  defaultTab?: string
}

export function HubPage({ tabs, defaultTab }: HubPageProps) {
  const [searchParams, setSearchParams] = useSearchParams()
  const pendingCount = useSaltKeysStore((s) => s.pendingCount)

  const activeKey = searchParams.get('tab') ?? defaultTab ?? tabs[0]?.key
  const activeTab = tabs.find((t) => t.key === activeKey) ?? tabs[0]

  const ActiveComponent = activeTab?.component

  return (
    <>
      {/* Tab bar — breaks out of main's p-6 */}
      <div className="-mx-6 -mt-6 mb-4">
        <div className="bg-white border-b border-gray-200 px-6 flex items-end sticky top-0 z-10 shadow-xs">
          {tabs.map((tab) => {
            const isActive = tab.key === activeTab?.key
            const hasBadge = tab.showBadge && pendingCount > 0
            return (
              <button
                key={tab.key}
                onClick={() => setSearchParams({ tab: tab.key })}
                className={[
                  'flex items-center gap-2 px-5 py-3.5 text-sm font-medium transition-all',
                  'border-b-2 -mb-px whitespace-nowrap',
                  isActive
                    ? 'border-brand-600 text-brand-600 font-semibold'
                    : 'border-transparent text-gray-500 hover:text-gray-800 hover:border-gray-300',
                ].join(' ')}
              >
                <tab.icon size={16} />
                {tab.label}
                {hasBadge && (
                  <span className="ml-1 px-1.5 py-0.5 rounded-full bg-amber-500 text-white text-[10px] font-bold leading-none">
                    {pendingCount > 9 ? '9+' : pendingCount}
                  </span>
                )}
              </button>
            )
          })}
        </div>
      </div>

      {/* Active tab content */}
      {ActiveComponent && <ActiveComponent />}
    </>
  )
}
