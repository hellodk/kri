import { NavLink } from 'react-router-dom'
import { useFilterStore } from '../../stores/filterStore'

const links = [
  { to: '/fleet',      label: 'Fleet',      icon: '⬡' },
  { to: '/drift',      label: 'Drift',      icon: '◈' },
  { to: '/sbom',       label: 'SBOM',       icon: '◉' },
  { to: '/groups',     label: 'Groups',     icon: '◫' },
  { to: '/executions', label: 'Executions', icon: '▷' },
  { to: '/playbooks',  label: 'Playbooks',  icon: '▤' },
  { to: '/audit',      label: 'Audit',      icon: '◎' },
  { to: '/settings',   label: 'Settings',   icon: '⚙' },
]

export function Sidebar() {
  const open = useFilterStore((s) => s.sidebarOpen)

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
        {open && <span className="text-white font-bold text-xl tracking-tight">kri</span>}
      </div>

      {/* Nav */}
      <ul className="flex-1 py-4 px-2 space-y-0.5">
        {links.map(({ to, label, icon }) => (
          <li key={to}>
            <NavLink
              to={to}
              title={!open ? label : undefined}
              className={({ isActive }) =>
                `group relative flex items-center gap-3 rounded-lg text-sm font-medium transition-all duration-150 ${
                  open ? 'px-3 py-2.5' : 'px-2.5 py-2.5 justify-center'
                } ${isActive
                  ? 'bg-brand-600/20 text-brand-300 border border-brand-600/30 shadow-sm shadow-brand-600/20'
                  : 'text-white/45 hover:text-white/90 hover:bg-white/5 border border-transparent'
                }`
              }
            >
              <span className="text-base flex-shrink-0 font-mono">{icon}</span>
              {open && <span>{label}</span>}
              {!open && (
                <span className="pointer-events-none absolute left-full ml-2 whitespace-nowrap rounded-md bg-gray-900 px-2 py-1 text-xs text-white opacity-0 group-hover:opacity-100 transition-opacity z-50 shadow-lg">
                  {label}
                </span>
              )}
            </NavLink>
          </li>
        ))}
      </ul>

      {/* Footer */}
      {open && (
        <div className="px-5 py-4 border-t border-white/10">
          <span className="text-white/20 text-xs font-mono">kri v0.1.0</span>
        </div>
      )}
    </nav>
  )
}
