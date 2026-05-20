import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { playbooksApi } from '../api/playbooks'
import type { PlaybookEntry } from '../api/playbooks'
import { Skeleton } from '../components/Skeleton'
import { ErrorState } from '../components/ErrorState'
import { PlaybookRunModal } from './PlaybookRunModal'

export function PlaybooksPage() {
  const [selected, setSelected] = useState<PlaybookEntry | null>(null)
  const [pendingRun, setPendingRun] = useState<PlaybookEntry | null>(null)

  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ['playbooks'],
    queryFn: playbooksApi.list,
    staleTime: 60_000,
  })

  const playbooks = data?.filter((e) => e.entry_type === 'playbook') ?? []
  const roles = data?.filter((e) => e.entry_type === 'role') ?? []

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Playbooks</h1>
        <p className="text-gray-500 mt-1 text-sm">
          Run Ansible playbooks and roles from{' '}
          <code className="bg-gray-100 px-1 rounded text-xs">playbooks/</code>.
          Variable changes are committed to git before each run.
        </p>
      </div>

      {isLoading ? (
        <Skeleton rows={4} />
      ) : isError ? (
        <ErrorState message="Failed to load playbooks" retry={refetch} />
      ) : (
        <>
          {playbooks.length > 0 && (
            <section className="space-y-3">
              <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide">Playbooks</h2>
              <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
                {playbooks.map((p) => (
                  <PlaybookCard key={p.filename} entry={p} onRun={() => setPendingRun(p)} />
                ))}
              </div>
            </section>
          )}

          {roles.length > 0 && (
            <section className="space-y-3">
              <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide">Roles</h2>
              <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
                {roles.map((r) => (
                  <PlaybookCard key={r.filename} entry={r} onRun={() => setPendingRun(r)} />
                ))}
              </div>
            </section>
          )}

          {playbooks.length === 0 && roles.length === 0 && (
            <div className="bg-white rounded-xl border border-gray-200 p-10 text-center text-gray-400 text-sm">
              No <code>.yml</code> files or roles found in <code>playbooks/</code>.
            </div>
          )}
        </>
      )}

      {/* Run confirmation */}
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
    </div>
  )
}

function PlaybookCard({ entry, onRun }: { entry: PlaybookEntry; onRun: () => void }) {
  const varCount = Object.keys(entry.default_vars).length
  return (
    <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-5 flex flex-col gap-3 hover:border-brand-300 transition-colors">
      <div className="flex items-start justify-between gap-2">
        <div>
          <p className="font-semibold text-gray-900 text-sm">{entry.name}</p>
          <p className="text-xs text-gray-400 font-mono mt-0.5">{entry.filename}</p>
        </div>
        <span className={`text-xs px-2 py-0.5 rounded font-medium flex-shrink-0 ${
          entry.entry_type === 'role'
            ? 'bg-purple-100 text-purple-700 border border-purple-200'
            : 'bg-brand-50 text-brand-700 border border-brand-200'
        }`}>
          {entry.entry_type}
        </span>
      </div>

      {entry.description && (
        <p className="text-sm text-gray-600 flex-1">{entry.description}</p>
      )}

      {varCount > 0 && (
        <div className="bg-gray-50 rounded-lg border border-gray-100 p-2.5 space-y-1">
          <p className="text-xs font-medium text-gray-400 uppercase tracking-wide mb-1">Variables ({varCount})</p>
          {Object.entries(entry.default_vars).map(([k, v]) => (
            <div key={k} className="flex items-center gap-2 text-xs">
              <span className="font-mono text-gray-600 w-36 truncate">{k}</span>
              <span className="font-mono text-gray-400 truncate">{String(v)}</span>
            </div>
          ))}
        </div>
      )}

      <button
        onClick={onRun}
        className="mt-auto px-4 py-2 bg-brand-600 text-white text-sm font-medium rounded-lg hover:bg-brand-700 shadow-sm"
      >
        Run
      </button>
    </div>
  )
}
