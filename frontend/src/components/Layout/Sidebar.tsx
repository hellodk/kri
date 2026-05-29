import { NavLink, useLocation } from 'react-router-dom'
import { useFilterStore } from '../../stores/filterStore'
import { useSaltKeysStore } from '../../stores/saltKeysStore'

// Hub nav entries — children live as tabs inside the hub page
const HUB_LINKS = [
  { to: '/overview',   label: 'Overview',   icon: '⊞' },
  { to: '/compliance', label: 'Compliance', icon: '◑' },
  { to: '/automation', label: 'Automation', icon: '▷', showBadge: true },
] as const

// System entries keep their child items (no hub)
const SYSTEM_LINKS = [
  { to: '/audit',    label: 'Audit',    icon: '◎' },
  { to: '/settings', label: 'Settings', icon: '⚙' },
] as const

type LinkDef = { to: string; label: string; icon: string; showBadge?: boolean }

export function Sidebar() {
  const open = useFilterStore((s) => s.sidebarOpen)
  const pendingCount = useSaltKeysStore((s) => s.pendingCount)
  const { pathname } = useLocation()

  const renderLink = (link: LinkDef, isHubLink: boolean) => {
    // Hub links use prefix matching (any sub-path counts as active)
    const isActive = isHubLink
      ? pathname.startsWith(link.to)
      : pathname === link.to || pathname.startsWith(link.to + '/')

    const hasBadge = link.showBadge && pendingCount > 0

    return (
      <li key={link.to}>
        <NavLink
          to={link.to}
          end={!isHubLink}
          title={!open ? link.label : undefined}
          className={`group relative flex items-center gap-3 rounded-lg text-sm font-medium transition-all duration-150 ${
            open ? 'px-3 py-2.5' : 'px-2.5 py-2.5 justify-center'
          } ${
            isActive
              ? 'bg-brand-600/20 text-brand-300 border border-brand-600/30 shadow-sm shadow-brand-600/20'
              : 'text-white/70 hover:text-white/90 hover:bg-white/5 border border-transparent'
          }`}
        >
          <span className="relative text-base flex-shrink-0 font-mono">
            {link.icon}
            {hasBadge && (
              <span className="absolute -top-1.5 -right-1.5 w-3.5 h-3.5 rounded-full bg-amber-500 border border-[#0f0f23] text-[8px] font-bold text-white flex items-center justify-center">
                {pendingCount > 9 ? '9+' : pendingCount}
              </span>
            )}
          </span>
          {open && (
            <span className="flex items-center gap-2 flex-1">
              {link.label}
              {hasBadge && (
                <span className="ml-auto px-1.5 py-0.5 rounded-full bg-amber-500 text-white text-[10px] font-bold leading-none">
                  {pendingCount}
                </span>
              )}
            </span>
          )}
          {!open && (
            <span className="pointer-events-none absolute left-full ml-2 whitespace-nowrap rounded-md bg-gray-900 px-2 py-1 text-xs text-white opacity-0 group-hover:opacity-100 transition-opacity z-50 shadow-lg">
              {link.label}
              {hasBadge ? ` (${pendingCount} pending)` : ''}
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
        {/* Hub links */}
        {HUB_LINKS.map((link) => renderLink(link, true))}

        {/* Divider before system links */}
        <li>
          <div className="mx-2 my-3 border-t border-white/10" />
        </li>

        {/* System links */}
        {SYSTEM_LINKS.map((link) => renderLink(link, false))}
      </ul>
    </nav>
  )
}
