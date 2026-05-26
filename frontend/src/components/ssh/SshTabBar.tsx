/**
 * SshTabBar — horizontal tab strip for managing multiple SSH sessions.
 *
 * Design tokens (light theme):
 *   Background  #F9FAFB
 *   Active tab  bg-white + border-b-[#2563EB]
 *   Inactive    bg-gray-100 text-gray-600 hover:bg-gray-200
 *   Close btn   hover:text-red-600
 */

export interface SshTab {
  id: string
  nodeId: string
  nodeName: string
  sessionId: string | null
}

interface SshTabBarProps {
  tabs: SshTab[]
  activeTabId: string
  onTabSelect: (id: string) => void
  onTabClose: (id: string) => void
  onNewTab: () => void
}

export function SshTabBar({
  tabs,
  activeTabId,
  onTabSelect,
  onTabClose,
  onNewTab,
}: SshTabBarProps) {
  return (
    <div
      className="flex items-end gap-0.5 px-2 pt-1 bg-gray-900 border-b border-gray-700 overflow-x-auto shrink-0"
      style={{ minHeight: 38 }}
      role="tablist"
      aria-label="SSH Sessions"
    >
      {tabs.map((tab, idx) => {
        const isActive = tab.id === activeTabId
        return (
          <div
            key={tab.id}
            role="tab"
            aria-selected={isActive}
            aria-controls={`ssh-panel-${tab.id}`}
            id={`ssh-tab-${tab.id}`}
            className={[
              'flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-t select-none cursor-pointer shrink-0 max-w-[180px] transition-colors',
              isActive
                ? 'bg-gray-950 text-cyan-400 border-t border-x border-gray-700 border-b-0'
                : 'bg-gray-800 text-gray-400 hover:bg-gray-750 hover:text-gray-200 border border-transparent',
            ].join(' ')}
            onClick={() => onTabSelect(tab.id)}
            title={`SSH → ${tab.nodeName} (session ${idx + 1})`}
          >
            {/* Status dot */}
            <span
              className={[
                'w-1.5 h-1.5 rounded-full shrink-0',
                isActive ? 'bg-emerald-400' : 'bg-gray-600',
              ].join(' ')}
            />
            {/* Label — truncated */}
            <span className="truncate leading-tight">
              {tab.nodeName}
            </span>
            {tabs.length > 1 && (
              <span className="ml-0.5 text-xs leading-none shrink-0">
                {idx + 1}
              </span>
            )}
            {/* Close button */}
            <button
              type="button"
              aria-label={`Close SSH session ${idx + 1} (${tab.nodeName})`}
              onClick={(e) => {
                e.stopPropagation()
                onTabClose(tab.id)
              }}
              className={[
                'ml-0.5 w-4 h-4 flex items-center justify-center rounded shrink-0 transition-colors',
                isActive
                  ? 'text-gray-500 hover:text-red-400 hover:bg-gray-800'
                  : 'text-gray-600 hover:text-red-400 hover:bg-gray-700',
              ].join(' ')}
            >
              ×
            </button>
          </div>
        )
      })}

      {/* New tab button */}
      <button
        type="button"
        aria-label="Open new SSH session to same node"
        onClick={onNewTab}
        className="flex items-center justify-center w-7 h-7 mb-0.5 ml-1 rounded text-gray-500 hover:text-gray-200 hover:bg-gray-700 transition-colors shrink-0 text-base font-light leading-none"
        title="Open new SSH session (same node)"
      >
        +
      </button>
    </div>
  )
}
