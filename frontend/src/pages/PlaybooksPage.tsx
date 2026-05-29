import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { playbooksApi } from '../api/playbooks'
import { ansibleApi } from '../api/ansible'
import type { PlaybookEntry } from '../api/playbooks'
import { Skeleton } from '../components/Skeleton'
import { ErrorState } from '../components/ErrorState'
import { PlaybookRunModal } from './PlaybookRunModal'
import { PlaybookDrawer } from '../components/PlaybookDrawer'
import { fuzzyAny } from '../utils/fuzzy'

function filterAndSort(entries: PlaybookEntry[], q: string): PlaybookEntry[] {
  if (!q) return entries
  return entries
    .map((e) => ({ e, score: fuzzyAny([e.name, e.filename], q) }))
    .filter(({ score }) => score > 0)
    .sort((a, b) => b.score - a.score)
    .map(({ e }) => e)
}

export function PlaybooksPage() {
  const [selected, setSelected] = useState<PlaybookEntry | null>(null)
  const [pendingRun, setPendingRun] = useState<PlaybookEntry | null>(null)
  const [openPlaybook, setOpenPlaybook] = useState<PlaybookEntry | null>(null)
  const [search, setSearch] = useState('')

  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ['playbooks'],
    queryFn: playbooksApi.list,
    staleTime: 60_000,
  })

  const { data: settings } = useQuery({
    queryKey: ['settings'],
    queryFn: ansibleApi.getSettings,
    staleTime: 60_000,
  })

  const allPlaybooks = data?.filter((e) => e.entry_type === 'playbook') ?? []
  const allRoles = data?.filter((e) => e.entry_type === 'role') ?? []
  const playbooks = filterAndSort(allPlaybooks, search)
  const roles = filterAndSort(allRoles, search)

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Playbooks</h1>
        <p className="text-gray-500 mt-1 text-sm">
          Run Ansible playbooks and roles. Click <strong>Files</strong> to explore the dependency tree and edit files inline.
        </p>
      </div>

      {isLoading ? (
        <Skeleton rows={4} />
      ) : isError ? (
        <ErrorState message="Failed to load playbooks" retry={refetch} />
      ) : (
        <>
          {/* Stat row */}
          <div className="grid grid-cols-3 gap-4 mb-6">
            <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-5">
              <div className="text-xs font-semibold uppercase tracking-wide text-gray-400 mb-2">▤ Playbooks</div>
              <div className="text-4xl font-black text-gray-900">{allPlaybooks.length}</div>
            </div>
            <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-5">
              <div className="text-xs font-semibold uppercase tracking-wide text-gray-400 mb-2">⊡ Roles</div>
              <div className="text-4xl font-black text-gray-900">{allRoles.length}</div>
            </div>
            <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-5">
              <div className="text-xs font-semibold uppercase tracking-wide text-gray-400 mb-2">⊞ Ansible</div>
              <div className={`text-lg font-bold ${settings?.ansible_endpoint_url ? 'text-emerald-600' : 'text-amber-600'}`}>
                {settings?.ansible_endpoint_url ? 'Connected' : 'Not configured'}
              </div>
              <div className="text-xs text-gray-400 mt-1 truncate">{settings?.ansible_endpoint_url ?? 'Set in Settings'}</div>
            </div>
          </div>

          {/* Fuzzy search */}
          <div className="relative">
            <span className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400 text-sm select-none">⌕</span>
            <input
              type="search"
              placeholder="Search playbooks and roles… (fuzzy: type 'bsmc' to match 'bootstrap_mac_mini')"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="w-full pl-8 pr-4 py-2.5 bg-white border border-gray-200 rounded-xl text-sm text-gray-900 placeholder-gray-400 shadow-sm focus:outline-none focus:border-brand-500 focus:ring-1 focus:ring-brand-500 transition-colors"
            />
            {search && (
              <button
                onClick={() => setSearch('')}
                className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600 text-lg leading-none"
              >
                ×
              </button>
            )}
          </div>

          {playbooks.length === 0 && roles.length === 0 && !search && (
            <div className="bg-white rounded-xl border border-gray-200 p-10 text-center text-gray-400 text-sm">
              No <code>.yml</code> files or roles found in <code>playbooks/</code>.
            </div>
          )}

          {playbooks.length === 0 && roles.length === 0 && search && (
            <div className="bg-white rounded-xl border border-gray-200 p-10 text-center text-gray-400 text-sm">
              No matches for <strong className="text-gray-600">"{search}"</strong>
              <button onClick={() => setSearch('')} className="ml-2 text-brand-600 hover:underline">clear</button>
            </div>
          )}

          {/* Playbooks table */}
          {playbooks.length > 0 && (
            <div className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden mb-6">
              <div className="px-5 py-3 border-b border-gray-100 flex items-center justify-between">
                <span className="text-sm font-semibold text-gray-700">Playbooks</span>
                <span className="text-xs text-gray-400">
                  {search ? `${playbooks.length} of ${allPlaybooks.length}` : `${allPlaybooks.length} total`}
                </span>
              </div>
              <table className="w-full">
                <thead>
                  <tr className="border-b border-gray-100 bg-gray-50">
                    <th className="px-5 py-2.5 text-left text-xs font-semibold text-gray-500 uppercase tracking-wide">Name</th>
                    <th className="px-5 py-2.5 text-left text-xs font-semibold text-gray-500 uppercase tracking-wide hidden md:table-cell">File</th>
                    <th className="px-5 py-2.5 text-center text-xs font-semibold text-gray-500 uppercase tracking-wide">Vars</th>
                    <th className="px-5 py-2.5 text-right text-xs font-semibold text-gray-500 uppercase tracking-wide">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {playbooks.map((p) => (
                    <tr key={p.filename} className="border-b border-gray-50 hover:bg-gray-50 transition-colors last:border-0">
                      <td className="px-5 py-3">
                        <div className="flex items-center gap-2">
                          <span className="text-xs px-1.5 py-0.5 rounded bg-brand-50 text-brand-700 font-semibold">▤</span>
                          <span className="font-medium text-gray-900 text-sm">{p.name}</span>
                          {p.lint_errors.length > 0 && (
                            <span className="text-xs px-1.5 py-0.5 rounded bg-red-50 text-red-600 font-medium border border-red-200" title={p.lint_errors.join('\n')}>
                              ⚠ errors
                            </span>
                          )}
                        </div>
                        {p.description && (
                          <p className="text-xs text-gray-400 mt-0.5 ml-7">{p.description}</p>
                        )}
                      </td>
                      <td className="px-5 py-3 hidden md:table-cell">
                        <span className="font-mono text-xs text-gray-400">{p.filename}</span>
                      </td>
                      <td className="px-5 py-3 text-center">
                        {Object.keys(p.default_vars).length > 0 && (
                          <span className="text-xs px-2 py-0.5 rounded-full bg-gray-100 text-gray-600 font-medium">
                            {Object.keys(p.default_vars).length} vars
                          </span>
                        )}
                      </td>
                      <td className="px-5 py-3">
                        <div className="flex items-center justify-end gap-2">
                          <button
                            onClick={() => setOpenPlaybook(p)}
                            className="px-3 py-1.5 text-xs font-medium border border-gray-200 text-gray-600 rounded-lg hover:bg-gray-50 transition-colors"
                          >
                            📁 Files
                          </button>
                          <button
                            onClick={() => setPendingRun(p)}
                            disabled={p.lint_errors.length > 0}
                            className="px-3 py-1.5 text-xs font-medium bg-brand-600 text-white rounded-lg hover:bg-brand-700 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
                          >
                            ▷ Run
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {/* Roles table */}
          {roles.length > 0 && (
            <div className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden mb-6">
              <div className="px-5 py-3 border-b border-gray-100 flex items-center justify-between">
                <span className="text-sm font-semibold text-gray-700">Roles</span>
                <span className="text-xs text-gray-400">
                  {search ? `${roles.length} of ${allRoles.length}` : `${allRoles.length} total`}
                </span>
              </div>
              <table className="w-full">
                <thead>
                  <tr className="border-b border-gray-100 bg-gray-50">
                    <th className="px-5 py-2.5 text-left text-xs font-semibold text-gray-500 uppercase tracking-wide">Name</th>
                    <th className="px-5 py-2.5 text-left text-xs font-semibold text-gray-500 uppercase tracking-wide hidden md:table-cell">File</th>
                    <th className="px-5 py-2.5 text-center text-xs font-semibold text-gray-500 uppercase tracking-wide">Vars</th>
                    <th className="px-5 py-2.5 text-right text-xs font-semibold text-gray-500 uppercase tracking-wide">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {roles.map((r) => (
                    <tr key={r.filename} className="border-b border-gray-50 hover:bg-gray-50 transition-colors last:border-0">
                      <td className="px-5 py-3">
                        <div className="flex items-center gap-2">
                          <span className="text-xs px-1.5 py-0.5 rounded bg-gray-100 text-gray-600 font-semibold">⊡</span>
                          <span className="font-medium text-gray-900 text-sm">{r.name}</span>
                          {r.lint_errors.length > 0 && (
                            <span className="text-xs px-1.5 py-0.5 rounded bg-red-50 text-red-600 font-medium border border-red-200" title={r.lint_errors.join('\n')}>
                              ⚠ errors
                            </span>
                          )}
                        </div>
                        {r.description && (
                          <p className="text-xs text-gray-400 mt-0.5 ml-7">{r.description}</p>
                        )}
                      </td>
                      <td className="px-5 py-3 hidden md:table-cell">
                        <span className="font-mono text-xs text-gray-400">{r.filename}</span>
                      </td>
                      <td className="px-5 py-3 text-center">
                        {Object.keys(r.default_vars).length > 0 && (
                          <span className="text-xs px-2 py-0.5 rounded-full bg-gray-100 text-gray-600 font-medium">
                            {Object.keys(r.default_vars).length} vars
                          </span>
                        )}
                      </td>
                      <td className="px-5 py-3">
                        <div className="flex items-center justify-end gap-2">
                          <button
                            onClick={() => setOpenPlaybook(r)}
                            className="px-3 py-1.5 text-xs font-medium border border-gray-200 text-gray-600 rounded-lg hover:bg-gray-50 transition-colors"
                          >
                            📁 Files
                          </button>
                          <button
                            onClick={() => setPendingRun(r)}
                            disabled={r.lint_errors.length > 0}
                            className="px-3 py-1.5 text-xs font-medium bg-brand-600 text-white rounded-lg hover:bg-brand-700 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
                          >
                            ▷ Run
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}

      {pendingRun && !selected && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div className="bg-white rounded-2xl shadow-2xl p-6 w-full max-w-sm mx-4 space-y-4">
            <h2 className="text-lg font-bold text-gray-900">Run playbook?</h2>
            <p className="text-sm text-gray-600">
              <span className="font-semibold">{pendingRun.name}</span> will run against real infrastructure. This cannot be undone.
            </p>
            <p className="text-xs text-gray-400 font-mono">{pendingRun.filename}</p>
            <div className="flex gap-3">
              <button onClick={() => setPendingRun(null)}
                className="flex-1 py-2.5 border border-gray-300 text-gray-700 rounded-lg text-sm font-medium hover:bg-gray-50">
                Cancel
              </button>
              <button onClick={() => { setSelected(pendingRun); setPendingRun(null) }}
                className="flex-1 py-2.5 bg-brand-600 text-white rounded-lg text-sm font-medium hover:bg-brand-700">
                Continue
              </button>
            </div>
          </div>
        </div>
      )}

      {selected && <PlaybookRunModal playbook={selected} onClose={() => setSelected(null)} />}

      {openPlaybook && <PlaybookDrawer playbook={openPlaybook} onClose={() => setOpenPlaybook(null)} />}
    </div>
  )
}
