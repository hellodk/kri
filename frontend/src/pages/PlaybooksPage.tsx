import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { playbooksApi } from '../api/playbooks'
import { ansibleApi } from '../api/ansible'
import type { PlaybookEntry } from '../api/playbooks'
import type { PlatformSettings } from '../api/ansible'
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

  const { data: settings } = useQuery({
    queryKey: ['settings'],
    queryFn: ansibleApi.getSettings,
    staleTime: 60_000,
  })

  const playbooks = data?.filter((e) => e.entry_type === 'playbook') ?? []
  const roles = data?.filter((e) => e.entry_type === 'role') ?? []

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Playbooks</h1>
        <p className="text-gray-500 mt-1 text-sm">
          Run Ansible playbooks and roles. Click <strong>View YAML</strong> to inspect content and runtime configuration before running.
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
                  <PlaybookCard key={p.filename} entry={p} settings={settings ?? null} onRun={() => setPendingRun(p)} />
                ))}
              </div>
            </section>
          )}

          {roles.length > 0 && (
            <section className="space-y-3">
              <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide">Roles</h2>
              <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
                {roles.map((r) => (
                  <PlaybookCard key={r.filename} entry={r} settings={settings ?? null} onRun={() => setPendingRun(r)} />
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

function PlaybookCard({
  entry,
  settings,
  onRun,
}: {
  entry: PlaybookEntry
  settings: PlatformSettings | null
  onRun: () => void
}) {
  const [showYaml, setShowYaml] = useState(false)
  const [showConfig, setShowConfig] = useState(false)

  const { data: yamlData, isLoading: yamlLoading } = useQuery({
    queryKey: ['playbook-content', entry.filename],
    queryFn: () => ansibleApi.playbookContent(entry.filename),
    enabled: showYaml,
    staleTime: 5 * 60_000,
  })

  const varCount = Object.keys(entry.default_vars).length

  const kriApiUrl = settings?.kri_api_url ?? null
  const saltMaster = settings?.salt_master_address ?? null
  const ingestUrl = kriApiUrl
    ? `${kriApiUrl.replace(/\/$/, '')}/api/v1/ingest`
    : saltMaster
      ? `http://${saltMaster}/api/v1/ingest`
      : null

  const configRows: { label: string; value: string; warn?: boolean }[] = [
    {
      label: 'salt_master_address',
      value: saltMaster ?? '(not configured)',
      warn: !saltMaster,
    },
    {
      label: 'ingest_url',
      value: ingestUrl ?? '(not configured — set kri External URL in Settings)',
      warn: !ingestUrl,
    },
    {
      label: 'controller_pubkey',
      value: settings?.controller_pubkey ? 'configured' : '(not generated)',
      warn: !settings?.controller_pubkey,
    },
    {
      label: 'ssh_user (default)',
      value: settings?.ssh_bootstrap_username ?? '(not set — per-node creds required)',
      warn: !settings?.ssh_bootstrap_username,
    },
    {
      label: 'playbooks_dir',
      value: settings?.playbooks_dir ?? '<repo>/playbooks (default)',
    },
    {
      label: 'pillar_dir',
      value: settings?.pillar_dir ?? '/srv/salt/pillar (default)',
    },
  ]

  return (
    <div className="bg-white rounded-xl border border-gray-200 shadow-sm flex flex-col hover:border-brand-300 transition-colors">
      {/* Header */}
      <div className="p-5 flex flex-col gap-3 flex-1">
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
          <p className="text-sm text-gray-600">{entry.description}</p>
        )}

        {varCount > 0 && (
          <div className="bg-gray-50 rounded-lg border border-gray-100 p-2.5 space-y-1">
            <p className="text-xs font-medium text-gray-400 uppercase tracking-wide mb-1">Default Variables ({varCount})</p>
            {Object.entries(entry.default_vars).map(([k, v]) => (
              <div key={k} className="flex items-center gap-2 text-xs">
                <span className="font-mono text-gray-600 w-36 truncate">{k}</span>
                <span className="font-mono text-gray-400 truncate">{String(v)}</span>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* YAML viewer */}
      {showYaml && (
        <div className="border-t border-gray-100">
          {/* Tab bar */}
          <div className="flex border-b border-gray-100">
            <button
              onClick={() => setShowConfig(false)}
              className={`flex-1 px-3 py-2 text-xs font-medium transition-colors ${
                !showConfig ? 'text-brand-700 border-b-2 border-brand-600 bg-brand-50/40' : 'text-gray-500 hover:text-gray-700'
              }`}
            >
              YAML
            </button>
            <button
              onClick={() => setShowConfig(true)}
              className={`flex-1 px-3 py-2 text-xs font-medium transition-colors ${
                showConfig ? 'text-brand-700 border-b-2 border-brand-600 bg-brand-50/40' : 'text-gray-500 hover:text-gray-700'
              }`}
            >
              Runtime Config
            </button>
          </div>

          {!showConfig ? (
            <div className="max-h-72 overflow-auto bg-gray-950 rounded-b-none">
              {yamlLoading ? (
                <p className="text-xs text-gray-400 p-4">Loading…</p>
              ) : yamlData ? (
                <pre className="text-xs font-mono text-green-300 p-4 whitespace-pre overflow-x-auto leading-relaxed">
                  {yamlData.content}
                </pre>
              ) : (
                <p className="text-xs text-red-400 p-4">Failed to load YAML</p>
              )}
            </div>
          ) : (
            <div className="max-h-72 overflow-auto bg-gray-50 p-3 space-y-1.5">
              <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">
                Variables injected by kri at runtime
              </p>
              {configRows.map((row) => (
                <div key={row.label} className="flex gap-2 text-xs">
                  <span className="font-mono text-gray-500 w-44 shrink-0">{row.label}</span>
                  <span className={`font-mono truncate ${row.warn ? 'text-amber-600' : 'text-gray-800'}`}>
                    {row.value}
                  </span>
                </div>
              ))}
              <p className="text-xs text-gray-400 pt-2 border-t border-gray-200 mt-2">
                Per-node SSH credentials override the default SSH user when set on a node.
              </p>
            </div>
          )}
        </div>
      )}

      {/* Footer actions */}
      <div className="px-5 pb-5 pt-3 flex gap-2 border-t border-gray-100 mt-auto">
        <button
          onClick={() => { setShowYaml(!showYaml); if (showYaml) setShowConfig(false) }}
          className="flex-1 px-3 py-2 border border-gray-200 text-gray-600 text-xs font-medium rounded-lg hover:bg-gray-50"
        >
          {showYaml ? 'Hide' : 'View YAML'}
        </button>
        <button
          onClick={onRun}
          className="flex-1 px-3 py-2 bg-brand-600 text-white text-xs font-medium rounded-lg hover:bg-brand-700 shadow-sm"
        >
          Run
        </button>
      </div>
    </div>
  )
}
