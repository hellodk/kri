import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { playbooksApi } from '../api/playbooks'
import { ansibleApi } from '../api/ansible'
import { libraryApi } from '../api/playbookLibrary'
import type { PlaybookEntry } from '../api/playbooks'
import { Skeleton } from '../components/Skeleton'
import { ErrorState } from '../components/ErrorState'
import { PlaybookRunModal } from './PlaybookRunModal'
import { PlaybookDrawer } from '../components/PlaybookDrawer'
import { fuzzyAny } from '../utils/fuzzy'
import { ansibleCardCta } from '../lib/ansibleCta'
import { useToastStore } from '../stores/toastStore'

function filterAndSort(entries: PlaybookEntry[], q: string): PlaybookEntry[] {
  if (!q) return entries
  return entries
    .map((e) => ({ e, score: fuzzyAny([e.name, e.filename], q) }))
    .filter(({ score }) => score > 0)
    .sort((a, b) => b.score - a.score)
    .map(({ e }) => e)
}

interface PlaybookRowProps {
  p: PlaybookEntry
  badge: string
  badgeClass: string
  onRun: (p: PlaybookEntry) => void
  onFiles: (p: PlaybookEntry) => void
  onToggleFavorite: (p: PlaybookEntry) => void
  isFavPending: (catalogId: string | null) => boolean
}

function PlaybookRow({ p, badge, badgeClass, onRun, onFiles, onToggleFavorite, isFavPending }: PlaybookRowProps) {
  const isFav = !!p.is_favorite
  return (
    <tr className="border-b border-gray-50 hover:bg-gray-50 transition-colors last:border-0">
      <td className="px-3 py-3 w-8 text-center">
        {p.catalog_id ? (
          <button
            onClick={() => onToggleFavorite(p)}
            disabled={isFavPending(p.catalog_id)}
            title={isFav ? 'Remove from favorites' : 'Add to favorites'}
            className="leading-none disabled:opacity-40"
          >
            {isFav ? (
              <span className="text-amber-400 text-lg">★</span>
            ) : (
              <span className="text-gray-500 hover:text-amber-400 text-lg">☆</span>
            )}
          </button>
        ) : (
          <span className="text-gray-500 text-lg" title="Not in library">☆</span>
        )}
      </td>
      <td className="px-5 py-3">
        <div className="flex items-center gap-2">
          <span className={`text-xs px-1.5 py-0.5 rounded font-semibold ${badgeClass}`}>{badge}</span>
          <span className="font-medium text-gray-900 text-sm">{p.name}</span>
          {p.lint_errors.length > 0 && (
            <span
              className="text-xs px-1.5 py-0.5 rounded bg-red-50 text-red-600 font-medium border border-red-200"
              title={p.lint_errors.join('\n')}
            >
              ⚠ errors
            </span>
          )}
        </div>
        {p.description && (
          <p className="text-xs text-gray-600 mt-0.5 ml-7">{p.description}</p>
        )}
      </td>
      <td className="px-5 py-3 hidden md:table-cell">
        <span className="font-mono text-xs text-gray-600">{p.filename}</span>
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
            onClick={() => onFiles(p)}
            className="px-3 py-1.5 text-xs font-medium border border-gray-200 text-gray-600 rounded-lg hover:bg-gray-50 transition-colors"
          >
            📁 Files
          </button>
          <button
            onClick={() => onRun(p)}
            disabled={p.lint_errors.length > 0}
            className="px-3 py-1.5 text-xs font-medium bg-brand-600 text-white rounded-lg hover:bg-brand-700 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
          >
            ▷ Run
          </button>
        </div>
      </td>
    </tr>
  )
}

interface EntriesTableProps {
  title: string
  entries: PlaybookEntry[]
  allCount: number
  search: string
  entryType: 'playbook' | 'role'
  amberBg?: boolean
  onRun: (p: PlaybookEntry) => void
  onFiles: (p: PlaybookEntry) => void
  onToggleFavorite: (p: PlaybookEntry) => void
  isFavPending: (catalogId: string | null) => boolean
}

function EntriesTable({
  title,
  entries,
  allCount,
  search,
  entryType,
  amberBg = false,
  onRun,
  onFiles,
  onToggleFavorite,
  isFavPending,
}: EntriesTableProps) {
  const badge = entryType === 'playbook' ? '▤' : '⊡'
  const badgeClass =
    entryType === 'playbook'
      ? 'bg-brand-50 text-brand-700'
      : 'bg-gray-100 text-gray-600'

  const containerClass = amberBg
    ? 'bg-amber-50 rounded-xl border border-amber-200 shadow-sm overflow-hidden mb-6'
    : 'bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden mb-6'

  const headerBorderClass = amberBg ? 'border-amber-100' : 'border-gray-100'
  const theadClass = amberBg ? 'border-b border-amber-100 bg-amber-100/60' : 'border-b border-gray-100 bg-gray-50'

  return (
    <div className={containerClass}>
      <div className={`px-5 py-3 border-b ${headerBorderClass} flex items-center justify-between`}>
        <span className="text-sm font-semibold text-gray-700">{title}</span>
        <span className="text-xs text-gray-600">
          {search ? `${entries.length} of ${allCount}` : `${allCount} total`}
        </span>
      </div>
      <table className="w-full">
        <thead>
          <tr className={theadClass}>
            <th className="px-3 py-2.5 w-8" />
            <th className="px-5 py-2.5 text-left text-xs font-semibold text-gray-500 uppercase tracking-wide">Name</th>
            <th className="px-5 py-2.5 text-left text-xs font-semibold text-gray-500 uppercase tracking-wide hidden md:table-cell">File</th>
            <th className="px-5 py-2.5 text-center text-xs font-semibold text-gray-500 uppercase tracking-wide">Vars</th>
            <th className="px-5 py-2.5 text-right text-xs font-semibold text-gray-500 uppercase tracking-wide">Actions</th>
          </tr>
        </thead>
        <tbody>
          {entries.map((p) => (
            <PlaybookRow
              key={p.filename}
              p={p}
              badge={badge}
              badgeClass={badgeClass}
              onRun={onRun}
              onFiles={onFiles}
              onToggleFavorite={onToggleFavorite}
              isFavPending={isFavPending}
            />
          ))}
        </tbody>
      </table>
    </div>
  )
}

export function PlaybooksPage() {
  const [selected, setSelected] = useState<PlaybookEntry | null>(null)
  const [pendingRun, setPendingRun] = useState<PlaybookEntry | null>(null)
  const [openPlaybook, setOpenPlaybook] = useState<PlaybookEntry | null>(null)
  const [search, setSearch] = useState('')
  const [pendingFavIds, setPendingFavIds] = useState<Set<string>>(new Set())

  const navigate = useNavigate()
  const toast = useToastStore((s) => s.add)
  const qc = useQueryClient()

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

  const { data: libraryData, isLoading: libLoading, isError: libError } = useQuery({
    queryKey: ['playbook-library'],
    queryFn: libraryApi.list,
    staleTime: 60_000,
  })

  const favMutation = useMutation<void, Error, { catalogId: string; isFav: boolean }>({
    mutationFn: async ({ catalogId, isFav }) => {
      if (isFav) {
        await libraryApi.removeFavorite(catalogId)
      } else {
        await libraryApi.addFavorite(catalogId)
      }
    },
    onMutate: ({ catalogId }) => {
      setPendingFavIds(prev => new Set([...prev, catalogId]))
    },
    onSettled: (_, __, { catalogId }) => {
      setPendingFavIds(prev => { const next = new Set(prev); next.delete(catalogId); return next })
      qc.invalidateQueries({ queryKey: ['playbooks'] })
      qc.invalidateQueries({ queryKey: ['playbook-library'] })
    },
    onError: () => toast('Failed to update favorite', 'error'),
  })

  const toggleFavorite = (p: PlaybookEntry) => {
    if (!p.catalog_id) return
    favMutation.mutate({ catalogId: p.catalog_id, isFav: !!p.is_favorite })
  }

  const allEntries = data ?? []
  const favorites = allEntries.filter((e) => e.is_favorite === true)

  // Non-favorite entries split by type
  const nonFavPlaybooks = allEntries.filter((e) => !e.is_favorite && e.entry_type === 'playbook')
  const nonFavRoles = allEntries.filter((e) => !e.is_favorite && e.entry_type === 'role')

  // Favorites split by type for rendering
  const favPlaybooks = favorites.filter((e) => e.entry_type === 'playbook')
  const favRoles = favorites.filter((e) => e.entry_type === 'role')

  // Filtered for display
  const filteredFavPlaybooks = filterAndSort(favPlaybooks, search)
  const filteredFavRoles = filterAndSort(favRoles, search)
  const playbooks = filterAndSort(nonFavPlaybooks, search)
  const roles = filterAndSort(nonFavRoles, search)

  const hasSources = libraryData !== undefined && libraryData.length > 0
  const hasEnabled = allEntries.length > 0

  const totalFiltered =
    filteredFavPlaybooks.length + filteredFavRoles.length + playbooks.length + roles.length

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Playbooks</h1>
        <p className="text-gray-500 mt-1 text-sm">
          Run Ansible playbooks and roles. Click <strong>Files</strong> to explore the dependency tree and edit files inline.
        </p>
      </div>

      {isLoading || libLoading ? (
        <Skeleton rows={4} />
      ) : isError || libError ? (
        <ErrorState message="Failed to load playbooks" retry={refetch} />
      ) : !hasEnabled && !hasSources ? (
        /* Empty state 1: no sources configured */
        <div className="bg-white rounded-xl border border-gray-200 p-12 text-center">
          <div className="text-5xl mb-4">🔌</div>
          <h2 className="text-lg font-semibold text-gray-800 mb-2">No playbook sources configured</h2>
          <p className="text-sm text-gray-500 max-w-sm mx-auto mb-6">
            Add a git repo or local directory under Settings → Sources, then enable playbooks from the library.
          </p>
          <button
            onClick={() => navigate('/settings?tab=Advanced')}
            className="px-4 py-2 bg-brand-600 text-white rounded-lg text-sm font-medium hover:bg-brand-700 transition-colors"
          >
            Go to Sources →
          </button>
        </div>
      ) : !hasEnabled && hasSources ? (
        /* Empty state 2: sources exist but nothing enabled */
        <div className="bg-white rounded-xl border border-gray-200 p-12 text-center">
          <div className="text-5xl mb-4">📚</div>
          <h2 className="text-lg font-semibold text-gray-800 mb-2">No playbooks enabled yet</h2>
          <p className="text-sm text-gray-500 max-w-sm mx-auto mb-1">
            Playbooks must be enabled from the library before operators can run them.
          </p>
          <p className="text-sm text-gray-500 max-w-sm mx-auto mb-6">
            Administrators can manage the library under Settings → Playbook Library.
          </p>
          <button
            onClick={() => navigate('/settings?tab=Playbook+Library')}
            className="px-4 py-2 bg-brand-600 text-white rounded-lg text-sm font-medium hover:bg-brand-700 transition-colors"
          >
            Browse Library →
          </button>
        </div>
      ) : (
        <>
          {/* Stat cards */}
          <div className="grid grid-cols-3 gap-4 mb-6">
            <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-5">
              <div className="text-xs font-semibold uppercase tracking-wide text-gray-600 mb-2">▤ Enabled</div>
              <div className="text-4xl font-black text-gray-900">{allEntries.length}</div>
            </div>
            <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-5">
              <div className="text-xs font-semibold uppercase tracking-wide text-gray-600 mb-2">★ Favorites</div>
              <div className="text-4xl font-black text-amber-500">{favorites.length}</div>
            </div>
            {(() => {
              const cta = ansibleCardCta(settings?.ansible_endpoint_url)
              return (
                <button
                  type="button"
                  onClick={() => navigate(cta.route)}
                  title="Configure in Settings → Integrations"
                  className="bg-white rounded-xl border border-gray-200 shadow-sm p-5 text-left w-full cursor-pointer hover:border-brand-400 hover:shadow-md transition-colors focus:outline-none focus:ring-2 focus:ring-brand-500"
                >
                  <div className="text-xs font-semibold uppercase tracking-wide text-gray-600 mb-2">⊞ Ansible</div>
                  <div className={`text-lg font-bold ${settings?.ansible_endpoint_url ? 'text-emerald-600' : 'text-amber-600'}`}>
                    {cta.status}
                  </div>
                  <div className="text-xs text-gray-600 mt-1 truncate underline decoration-dotted underline-offset-2">{cta.hint}</div>
                </button>
              )
            })()}
          </div>

          {/* Fuzzy search */}
          <div className="relative">
            <span className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-500 text-sm select-none">⌕</span>
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
                className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-500 hover:text-gray-700 text-lg leading-none"
              >
                ×
              </button>
            )}
          </div>

          {totalFiltered === 0 && search && (
            <div className="bg-white rounded-xl border border-gray-200 p-10 text-center text-gray-600 text-sm">
              No matches for <strong className="text-gray-900">"{search}"</strong>
              <button onClick={() => setSearch('')} className="ml-2 text-brand-600 hover:underline">clear</button>
            </div>
          )}

          {/* Favorites section — floats to top */}
          {favorites.length > 0 && (filteredFavPlaybooks.length > 0 || filteredFavRoles.length > 0) && (
            <div className="bg-amber-50 rounded-xl border border-amber-200 shadow-sm overflow-hidden mb-6">
              <div className="px-5 py-3 border-b border-amber-100 flex items-center justify-between">
                <span className="text-sm font-semibold text-amber-800">★ Favorites</span>
                <span className="text-xs text-amber-600">{favorites.length} total</span>
              </div>
              <table className="w-full">
                <thead>
                  <tr className="border-b border-amber-100 bg-amber-100/60">
                    <th className="px-3 py-2.5 w-8" />
                    <th className="px-5 py-2.5 text-left text-xs font-semibold text-gray-500 uppercase tracking-wide">Name</th>
                    <th className="px-5 py-2.5 text-left text-xs font-semibold text-gray-500 uppercase tracking-wide hidden md:table-cell">File</th>
                    <th className="px-5 py-2.5 text-center text-xs font-semibold text-gray-500 uppercase tracking-wide">Vars</th>
                    <th className="px-5 py-2.5 text-right text-xs font-semibold text-gray-500 uppercase tracking-wide">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredFavPlaybooks.map((p) => (
                    <PlaybookRow
                      key={`fav-pb-${p.filename}`}
                      p={p}
                      badge="▤"
                      badgeClass="bg-brand-50 text-brand-700"
                      onRun={setPendingRun}
                      onFiles={setOpenPlaybook}
                      onToggleFavorite={toggleFavorite}
                      isFavPending={(id) => pendingFavIds.has(id ?? '')}
                    />
                  ))}
                  {filteredFavRoles.map((r) => (
                    <PlaybookRow
                      key={`fav-role-${r.filename}`}
                      p={r}
                      badge="⊡"
                      badgeClass="bg-gray-100 text-gray-600"
                      onRun={setPendingRun}
                      onFiles={setOpenPlaybook}
                      onToggleFavorite={toggleFavorite}
                      isFavPending={(id) => pendingFavIds.has(id ?? '')}
                    />
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {/* Playbooks table */}
          {playbooks.length > 0 && (
            <EntriesTable
              title="Playbooks"
              entries={playbooks}
              allCount={nonFavPlaybooks.length}
              search={search}
              entryType="playbook"
              onRun={setPendingRun}
              onFiles={setOpenPlaybook}
              onToggleFavorite={toggleFavorite}
              isFavPending={(id) => pendingFavIds.has(id ?? '')}
            />
          )}

          {/* Roles table */}
          {roles.length > 0 && (
            <EntriesTable
              title="Roles"
              entries={roles}
              allCount={nonFavRoles.length}
              search={search}
              entryType="role"
              onRun={setPendingRun}
              onFiles={setOpenPlaybook}
              onToggleFavorite={toggleFavorite}
              isFavPending={(id) => pendingFavIds.has(id ?? '')}
            />
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
            <p className="text-xs text-gray-600 font-mono">{pendingRun.filename}</p>
            <div className="flex gap-3">
              <button
                onClick={() => setPendingRun(null)}
                className="flex-1 py-2.5 border border-gray-300 text-gray-700 rounded-lg text-sm font-medium hover:bg-gray-50"
              >
                Cancel
              </button>
              <button
                onClick={() => { setSelected(pendingRun); setPendingRun(null) }}
                className="flex-1 py-2.5 bg-brand-600 text-white rounded-lg text-sm font-medium hover:bg-brand-700"
              >
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
