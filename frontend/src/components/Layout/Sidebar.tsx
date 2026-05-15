import { NavLink } from 'react-router-dom'
import { useFilterStore } from '../../stores/filterStore'

const links = [
  { to: '/fleet', label: 'Fleet' },
  { to: '/drift', label: 'Drift' },
  { to: '/sbom', label: 'SBOM' },
  { to: '/groups', label: 'Groups' },
  { to: '/executions', label: 'Executions' },
]

export function Sidebar() {
  const open = useFilterStore((s) => s.sidebarOpen)
  if (!open) return null
  return (
    <nav className="w-56 flex-shrink-0 bg-gray-900 text-gray-100 min-h-screen flex flex-col">
      <div className="px-4 py-5 text-lg font-bold tracking-tight text-white border-b border-gray-700">
        Fleet Platform
      </div>
      <ul className="flex-1 py-4 space-y-1">
        {links.map(({ to, label }) => (
          <li key={to}>
            <NavLink
              to={to}
              className={({ isActive }) =>
                `block px-4 py-2 rounded-md text-sm font-medium transition-colors ${
                  isActive
                    ? 'bg-brand-600 text-white'
                    : 'text-gray-300 hover:bg-gray-800 hover:text-white'
                }`
              }
            >
              {label}
            </NavLink>
          </li>
        ))}
      </ul>
    </nav>
  )
}
