import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { libraryApi, type LibraryEntry } from '../api/playbookLibrary'
import { useToastStore } from '../stores/toastStore'
import { Skeleton } from '../components/Skeleton'
import { ErrorState } from '../components/ErrorState'

type FilterMode = 'all' | 'enabled' | 'disabled'

function groupBySource(entries: LibraryEntry[]) {
  const map = new Map<string, { label: string; key: string; entries: LibraryEntry[] }>()
  for (const e of entries) {
    if (!map.has(e.source_key)) {
      map.set(e.source_key, { label: e.source_label, key: e.source_key, entries: [] })
    }
    map.get(e.source_key)!.entries.push(e)
  }
  return [...map.values()]
}

export function PlaybookLibraryTab() {
  const qc = useQueryClient()
  const toast = useToastStore((s) => s.add)
  const [search, setSearch] = useState('')
  const [filter, setFilter] = useState<FilterMode>('all')
  const [expanded, setExpanded] = useState<Set<string>>(new Set())
  const [dismissed, setDismissed] = useState(false)
  // Per-entry pending state: tracks catalog_id (enabled) or filename (not-yet-enabled)
  const [pendingEntryIds, setPendingEntryIds] = useState<Set<string>>(new Set())
  // Per-source pending state: tracks source_key currently mutating via "Enable All"
  const [pendingSourceKeys, setPendingSourceKeys] = useState<Set<string>>(new Set())

  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ['playbook-library'],
    queryFn: libraryApi.list,
    staleTime: 30_000,
  })

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ['playbook-library'] })
    qc.invalidateQueries({ queryKey: ['playbooks'] })
  }

  // Returns a stable key for an entry regardless of whether it has a catalog_id yet
  const entryKey = (entry: LibraryEntry): string =>
    entry.catalog_id ?? entry.filename

  const enableMutation = useMutation({
    mutationFn: libraryApi.enable,
    onMutate: (vars) => {
      setPendingEntryIds((prev) => new Set([...prev, vars.filename]))
    },
    onSettled: (_data, _err, vars) => {
      setPendingEntryIds((prev) => {
        const next = new Set(prev)
        next.delete(vars.filename)
        return next
      })
    },
    onSuccess: () => {
      toast('Playbook enabled', 'success')
      invalidate()
    },
    onError: () => toast('Failed to enable playbook', 'error'),
  })

  const disableMutation = useMutation({
    mutationFn: (catalog_id: string) => libraryApi.disable(catalog_id),
    onMutate: (catalog_id) => {
      setPendingEntryIds((prev) => new Set([...prev, catalog_id]))
    },
    onSettled: (_data, _err, catalog_id) => {
      setPendingEntryIds((prev) => {
        const next = new Set(prev)
        next.delete(catalog_id)
        return next
      })
    },
    onSuccess: () => {
      toast('Playbook disabled', 'success')
      invalidate()
    },
    onError: () => toast('Failed to disable playbook', 'error'),
  })

  const enableSourceMutation = useMutation({
    mutationFn: (source_key: string) => libraryApi.enableSource(source_key),
    onMutate: (source_key) => {
      setPendingSourceKeys((prev) => new Set([...prev, source_key]))
    },
    onSettled: (_data, _err, source_key) => {
      setPendingSourceKeys((prev) => {
        const next = new Set(prev)
        next.delete(source_key)
        return next
      })
    },
    onSuccess: (result) => {
      toast(`Enabled ${result.enabled_count} playbooks`, 'success')
      invalidate()
    },
    onError: () => toast('Failed to enable source', 'error'),
  })

  if (isLoading) return <Skeleton rows={6} />

  if (isError) {
    return (
      <ErrorState
        message="Failed to load playbook library."
        retry={() => refetch()}
      />
    )
  }

  const entries = data ?? []
  const autoDisabled = entries.filter((e) => e.auto_disabled_at !== null)
  const totalEnabled = entries.filter((e) => e.enabled).length

  const filtered = entries.filter((e) => {
    const matchSearch =
      !search ||
      e.name.toLowerCase().includes(search.toLowerCase()) ||
      e.filename.toLowerCase().includes(search.toLowerCase())
    const matchFilter =
      filter === 'all' ||
      (filter === 'enabled' && e.enabled) ||
      (filter === 'disabled' && !e.enabled)
    return matchSearch && matchFilter
  })

  const groups = groupBySource(filtered)

  const toggle = (key: string) =>
    setExpanded((prev) => {
      const next = new Set(prev)
      if (next.has(key)) {
        next.delete(key)
      } else {
        next.add(key)
      }
      return next
    })

  return (
    <div className="space-y-4">
      {/* Auto-disable banner */}
      {!dismissed && autoDisabled.length > 0 && (
        <div className="flex items-start gap-3 bg-amber-50 border border-amber-200 rounded-xl px-4 py-3 text-sm text-amber-800">
          <span className="text-amber-500 mt-0.5 shrink-0">⚠</span>
          <div className="flex-1">
            <strong>
              {autoDisabled.length} playbook{autoDisabled.length > 1 ? 's' : ''} auto-disabled
            </strong>{' '}
            — their source files were removed during the last sync:{' '}
            {autoDisabled.map((e, i) => (
              <span key={e.filename}>
                {i > 0 && ', '}
                <code className="font-mono text-xs bg-amber-100 px-1 rounded">{e.filename}</code>
              </span>
            ))}
          </div>
          <button
            onClick={() => setDismissed(true)}
            className="text-amber-500 hover:text-amber-700 text-xl leading-none shrink-0"
          >
            ×
          </button>
        </div>
      )}

      {/* Controls */}
      <div className="flex items-center gap-3 flex-wrap">
        <span className="text-sm text-gray-500">
          {entries.length} discovered · {totalEnabled} enabled
        </span>
        <div className="flex-1" />
        <div className="flex gap-1">
          {(['all', 'enabled', 'disabled'] as FilterMode[]).map((f) => (
            <button
              key={f}
              onClick={() => setFilter(f)}
              className={`px-3 py-1 rounded-lg text-xs font-semibold transition-colors ${
                filter === f
                  ? 'bg-indigo-600 text-white'
                  : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
              }`}
            >
              {f.charAt(0).toUpperCase() + f.slice(1)}
            </button>
          ))}
        </div>
        <input
          type="search"
          placeholder="Search…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="w-48 px-3 py-1.5 text-sm border border-gray-200 rounded-lg focus:outline-hidden focus:ring-1 focus:ring-indigo-500"
        />
      </div>

      {/* Source accordions */}
      <div className="space-y-2">
        {groups.map((group) => {
          const isOpen = expanded.has(group.key)
          const groupEnabled = group.entries.filter((e) => e.enabled).length
          const isGit =
            group.key.startsWith('http') || group.key.startsWith('git@')

          return (
            <div
              key={group.key}
              className="bg-white border border-gray-200 rounded-xl overflow-hidden shadow-xs"
            >
              <button
                onClick={() => toggle(group.key)}
                className="w-full flex items-center justify-between px-5 py-3 text-left bg-gray-50 hover:bg-gray-100 transition-colors"
              >
                <div className="flex items-center gap-2">
                  <span className="text-sm font-bold text-gray-900">{group.label}</span>
                  <span className="text-xs px-1.5 py-0.5 rounded bg-gray-200 text-gray-600 font-medium">
                    {isGit ? 'git' : 'local'}
                  </span>
                </div>
                <div className="flex items-center gap-3">
                  <span className="text-xs text-gray-500">
                    {groupEnabled}/{group.entries.length} enabled
                  </span>
                  <button
                    onClick={(ev) => {
                      ev.stopPropagation()
                      enableSourceMutation.mutate(group.key)
                    }}
                    disabled={pendingSourceKeys.has(group.key)}
                    className="px-2.5 py-1 text-xs font-semibold border border-indigo-200 text-indigo-700 rounded-lg hover:bg-indigo-50 transition-colors disabled:opacity-50"
                  >
                    Enable All
                  </button>
                  <span className="text-gray-500 text-sm">{isOpen ? '▾' : '▸'}</span>
                </div>
              </button>

              {isOpen && (
                <div className="divide-y divide-gray-50">
                  {group.entries.map((entry) => (
                    <div
                      key={entry.filename}
                      className="flex items-center px-5 py-3 gap-3 hover:bg-gray-50"
                    >
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2 flex-wrap">
                          <span className="font-medium text-sm text-gray-900 truncate">
                            {entry.name}
                          </span>
                          <span
                            className={`text-xs px-1.5 py-0.5 rounded font-semibold ${
                              entry.entry_type === 'playbook'
                                ? 'bg-indigo-50 text-indigo-700'
                                : 'bg-gray-100 text-gray-600'
                            }`}
                          >
                            {entry.entry_type}
                          </span>
                          {entry.auto_disabled_at && (
                            <span className="text-xs px-1.5 py-0.5 rounded bg-amber-50 text-amber-700 border border-amber-200">
                              ⚠ removed from source
                            </span>
                          )}
                        </div>
                        {entry.description && (
                          <p className="text-xs text-gray-500 mt-0.5 truncate">
                            {entry.description}
                          </p>
                        )}
                        <p className="font-mono text-xs text-gray-500 mt-0.5 truncate">
                          {entry.filename}
                        </p>
                      </div>

                      {/* Toggle switch */}
                      <button
                        onClick={() => {
                          if (entry.enabled && entry.catalog_id) {
                            disableMutation.mutate(entry.catalog_id)
                          } else {
                            enableMutation.mutate({
                              source_key: entry.source_key,
                              source_label: entry.source_label,
                              filename: entry.filename,
                              entry_type: entry.entry_type,
                            })
                          }
                        }}
                        disabled={pendingEntryIds.has(entryKey(entry))}
                        className={`relative w-10 h-5 rounded-full transition-colors focus:outline-hidden disabled:opacity-50 shrink-0 ${
                          entry.enabled ? 'bg-emerald-500' : 'bg-gray-200'
                        }`}
                        title={entry.enabled ? 'Disable' : 'Enable'}
                      >
                        <span
                          className={`absolute top-0.5 w-4 h-4 bg-white rounded-full shadow transition-transform ${
                            entry.enabled ? 'left-5' : 'left-0.5'
                          }`}
                        />
                      </button>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )
        })}
      </div>

      {groups.length === 0 && (
        <div className="bg-white rounded-xl border border-gray-200 p-10 text-center text-gray-600 text-sm">
          {search
            ? `No matches for "${search}"`
            : 'No playbooks discovered across configured sources.'}
        </div>
      )}
    </div>
  )
}
