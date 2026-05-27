import { NavLink } from 'react-router-dom'
import { useFilterStore } from '../../stores/filterStore'
import { useSaltKeysStore } from '../../stores/saltKeysStore'

const NAV_GROUPS = [
  {
    label: 'Overview',
    items: [
      { to: '/dashboard',    label: 'Fleet Overview', icon: '⊞' },
      { to: '/fleet',        label: 'Fleet',          icon: '⬡' },
      { to: '/fleet-health', label: 'Fleet Health',   icon: '♥' },
      { to: '/groups',       label: 'Groups',         icon: '◫' },
    ],
  },
  {
    label: 'Compliance',
    items: [
      { to: '/drift',     label: 'Drift',     icon: '◑' },
      { to: '/baselines', label: 'Baselines', icon: '▬' },
      { to: '/sbom',      label: 'SBOM',      icon: '◉' },
      { to: '/security',  label: 'Security',  icon: '⛨' },
      { to: '/alerts',    label: 'Alerts',    icon: '◭' },
    ],
  },
  {
    label: 'Automation',
    items: [
      { to: '/executions',   label: 'Executions',   icon: '▷' },
      { to: '/playbooks',    label: 'Playbooks',    icon: '▤' },
      { to: '/provisioning', label: 'Provisioning', icon: '⊡' },
      { to: '/salt-ops',     label: 'Salt Ops',     icon: '▹' },
      { to: '/salt-keys',    label: 'Minion Keys',  icon: '⊗' },
    ],
  },
  {
    label: 'System',
    items: [
      { to: '/audit',    label: 'Audit',    icon: '◎' },
      { to: '/settings', label: 'Settings', icon: '⚙' },
    ],
  },
]

export function Sidebar() {
  const open = useFilterStore((s) => s.sidebarOpen)
  const pendingCount = useSaltKeysStore((s) => s.pendingCount)

  const renderItem = ({ to, label, icon }: { to: string; label: string; icon: string }) => {
    const isSaltKeys = to === '/salt-keys'
    const badge = isSaltKeys && pendingCount > 0

    return (
      <li key={to}>
        <NavLink
          to={to}
          title={!open ? label : undefined}
          className={({ isActive }) =>
            `group relative flex items-center gap-3 rounded-lg text-sm font-medium transition-all duration-150 ${
              open ? 'px-3 py-2.5' : 'px-2.5 py-2.5 justify-center'
            } ${isActive
              ? 'bg-brand-600/20 text-brand-300 border border-brand-600/30 shadow-sm shadow-brand-600/20'
              : 'text-white/70 hover:text-white/90 hover:bg-white/5 border border-transparent'
            }`
          }
        >
          <span className="relative text-base flex-shrink-0 font-mono">
            {icon}
            {badge && (
              <span className="absolute -top-1.5 -right-1.5 w-3.5 h-3.5 rounded-full bg-amber-500 border border-[#0f0f23] text-[8px] font-bold text-white flex items-center justify-center">
                {pendingCount > 9 ? '9+' : pendingCount}
              </span>
            )}
          </span>
          {open && (
            <span className="flex items-center gap-2 flex-1">
              {label}
              {badge && (
                <span className="ml-auto px-1.5 py-0.5 rounded-full bg-amber-500 text-white text-[10px] font-bold leading-none">
                  {pendingCount}
                </span>
              )}
            </span>
          )}
          {!open && (
            <span className="pointer-events-none absolute left-full ml-2 whitespace-nowrap rounded-md bg-gray-900 px-2 py-1 text-xs text-white opacity-0 group-hover:opacity-100 transition-opacity z-50 shadow-lg">
              {label}{badge ? ` (${pendingCount} pending)` : ''}
            </span>
          )}
        </NavLink>
      </li>
    )
  }

  return (
    <nav
      className={`flex-shrink-0 min-h-screen flex flex-col transition-all duration-200 ${open ? 'w-60' : 'w-16'}`}
      style={{ background: 'linear-gradient(180deg, #0f0f23 0%, #1a1a3e 100%)' }}
    >
      {/* Logo */}
      <div className={`flex items-center border-b border-white/10 ${open ? 'gap-3 px-5 py-5' : 'justify-center px-4 py-5'}`}>
        <div className="w-8 h-8 rounded-lg bg-brand-600 flex items-center justify-center flex-shrink-0 shadow-lg shadow-brand-600/40">
          <span className="text-white font-black text-sm tracking-tighter">k</span>
        </div>
        {open && (
          <div className="flex flex-col leading-none">
            <span className="text-white font-bold text-xl tracking-tight">kri</span>
            <span className="text-white/50 text-[11px] font-mono tracking-wide mt-0.5">v{__APP_VERSION__}</span>
          </div>
        )}
      </div>

      {/* Nav */}
      <ul className="flex-1 py-4 px-2 space-y-0.5 overflow-y-auto">
        {open
          ? NAV_GROUPS.map((group) => (
              <li key={group.label}>
                <p className="text-white/40 text-[10px] font-semibold tracking-widest uppercase px-3 pt-3 pb-1 select-none">
                  {group.label}
                </p>
                <ul className="space-y-0.5">
                  {group.items.map(renderItem)}
                </ul>
              </li>
            ))
          : NAV_GROUPS.flatMap((g) => g.items).map(renderItem)
        }
      </ul>

    </nav>
  )
}
