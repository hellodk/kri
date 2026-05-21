import { useEffect, useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { ansibleApi } from '../api/ansible'
import { playbookSourcesApi, type PlaybookSource } from '../api/playbookSources'
import { useToastStore } from '../stores/toastStore'

export function SettingsPage() {
  const qc = useQueryClient()
  const toast = useToastStore((s) => s.add)
  const [master, setMaster] = useState('')
  const [kriApiUrl, setKriApiUrl] = useState('')
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [ansibleEndpoint, setAnsibleEndpoint] = useState('')
  const [ansibleToken, setAnsibleToken] = useState('')
  const [playbooksDir, setPlaybooksDir] = useState('')
  const [pillarDir, setPillarDir] = useState('')

  const { data, isLoading } = useQuery({
    queryKey: ['settings'],
    queryFn: ansibleApi.getSettings,
  })

  useEffect(() => {
    if (data) {
      if (data.salt_master_address) setMaster(data.salt_master_address)
      if (data.kri_api_url) setKriApiUrl(data.kri_api_url)
      if (data.ssh_bootstrap_username) setUsername(data.ssh_bootstrap_username)
      if (data.ansible_endpoint_url) setAnsibleEndpoint(data.ansible_endpoint_url)
      if (data.playbooks_dir) setPlaybooksDir(data.playbooks_dir)
      if (data.pillar_dir) setPillarDir(data.pillar_dir)
    }
  }, [data])

  const saveMutation = useMutation({
    mutationFn: () => ansibleApi.updateSettings({
      salt_master_address: master || undefined,
      kri_api_url: kriApiUrl || undefined,
      ssh_bootstrap_username: username || undefined,
      ssh_bootstrap_password: password || undefined,
      ansible_endpoint_url: ansibleEndpoint || undefined,
      ansible_api_token: ansibleToken || undefined,
      playbooks_dir: playbooksDir || undefined,
      pillar_dir: pillarDir || undefined,
    }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['settings'] })
      toast('Settings saved')
      setPassword('')
    },
    onError: (e: Error) => toast(e.message, 'error'),
  })

  const computedIngestUrl = kriApiUrl
    ? `${kriApiUrl.replace(/\/$/, '')}/api/v1/ingest/grains`
    : master
      ? `http://${master}/api/v1/ingest/grains`
      : null

  if (isLoading) return <div className="p-6 text-gray-500">Loading…</div>

  const inputClass = 'w-full px-3 py-2 border border-gray-300 rounded-lg text-sm text-gray-900 focus:outline-none focus:border-brand-600'
  const monoInputClass = inputClass + ' font-mono'

  return (
    <div className="space-y-8 max-w-2xl">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Settings</h1>
        <p className="text-gray-500 mt-1">Configure the kri fleet platform — Salt master, SSH credentials, and Ansible integration.</p>
      </div>

      <div className="flex items-center gap-3">
        <div className="h-px flex-1 bg-gray-200" />
        <span className="text-xs font-semibold text-gray-400 uppercase tracking-wide">Required</span>
        <div className="h-px flex-1 bg-gray-200" />
      </div>

      {/* kri External URL */}
      <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-6 space-y-4">
        <div>
          <h2 className="text-base font-semibold text-gray-900">kri External URL</h2>
          <p className="text-sm text-gray-500 mt-1">
            The URL that Mac Minis use to call back to this kri server. Used to build the ingest endpoint
            that Salt minions POST grain data to. Must be reachable from all managed nodes — use the
            Tailscale IP or a LAN address, not <code className="text-xs bg-gray-100 px-1 rounded">localhost</code>.
          </p>
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">kri server URL</label>
          <input
            type="text"
            value={kriApiUrl}
            onChange={(e) => setKriApiUrl(e.target.value)}
            placeholder="http://100.89.50.27  or  http://kri.fleet.local"
            className={monoInputClass}
          />
          <p className="text-xs text-gray-400 mt-1">Include the scheme (<code>http://</code> or <code>https://</code>). No trailing slash. Port is optional — omit for standard ports 80/443.</p>
        </div>
        {computedIngestUrl && (
          <div className="bg-gray-50 border border-gray-200 rounded-lg px-3 py-2 flex items-center gap-2">
            <span className="text-xs text-gray-400 shrink-0">Computed ingest URL:</span>
            <code className="text-xs font-mono text-brand-700 truncate">{computedIngestUrl}</code>
          </div>
        )}
      </div>

      {/* Salt Master */}
      <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-6 space-y-4">
        <div>
          <h2 className="text-base font-semibold text-gray-900">Salt Master</h2>
          <p className="text-sm text-gray-500 mt-1">
            Hostname or IP of the Salt master. Written into <code className="text-xs bg-gray-100 px-1 rounded">/etc/salt/minion</code> on each node during bootstrap.
            If you are not running a dedicated Salt master, set this to the same address as the kri External URL above.
          </p>
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Master address (IP or DNS, no port)</label>
          <input
            type="text"
            value={master}
            onChange={(e) => setMaster(e.target.value)}
            placeholder="100.89.50.27  or  salt.fleet.local"
            className={monoInputClass}
          />
          <p className="text-xs text-gray-400 mt-1">Salt minions connect to this on port 4505/4506.</p>
        </div>
      </div>

      {/* SSH Bootstrap credentials */}
      <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-6 space-y-4">
        <div>
          <h2 className="text-base font-semibold text-gray-900">Default SSH Bootstrap Credentials</h2>
          <p className="text-sm text-gray-500 mt-1">
            Used as fallback when a node has no per-node SSH credentials set. Per-node credentials
            (set in <strong>Edit Node</strong>) always take priority over these global defaults.
          </p>
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">macOS admin username</label>
          <input type="text" value={username} onChange={(e) => setUsername(e.target.value)}
            placeholder="localadmin" className={inputClass} />
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">
            macOS admin password
            <span className="ml-2 text-xs font-normal text-gray-400">(stored encrypted, not shown after save)</span>
          </label>
          <div className="relative">
            <input
              type={showPassword ? 'text' : 'password'}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="Leave blank to keep existing"
              className={inputClass + ' pr-16'}
            />
            <button type="button" onClick={() => setShowPassword(!showPassword)}
              className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600 p-1">
              {showPassword ? (
                <svg xmlns="http://www.w3.org/2000/svg" className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13.875 18.825A10.05 10.05 0 0112 19c-4.478 0-8.268-2.943-9.543-7a9.97 9.97 0 011.563-3.029m5.858.908a3 3 0 114.243 4.243M9.878 9.878l4.242 4.242M9.88 9.88l-3.29-3.29m7.532 7.532l3.29 3.29M3 3l3.59 3.59m0 0A9.953 9.953 0 0112 5c4.478 0 8.268 2.943 9.543 7a10.025 10.025 0 01-4.132 4.411m0 0L21 21" />
                </svg>
              ) : (
                <svg xmlns="http://www.w3.org/2000/svg" className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
                </svg>
              )}
            </button>
          </div>
        </div>
      </div>

      {/* Controller SSH public key */}
      <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-6 space-y-3">
        <div>
          <h2 className="text-base font-semibold text-gray-900">Controller SSH Public Key</h2>
          <p className="text-sm text-gray-500 mt-1">
            Auto-generated key deployed to all Mac Minis during bootstrap via{' '}
            <code className="text-xs bg-gray-100 px-1 rounded">authorized_key</code>. After bootstrap, kri uses this key for all future SSH connections — no password needed.
          </p>
        </div>
        {data?.controller_pubkey ? (
          <div className="relative">
            <pre className="text-xs font-mono bg-gray-50 border border-gray-200 rounded-lg p-3 overflow-x-auto text-gray-700 whitespace-pre-wrap break-all">
              {data.controller_pubkey}
            </pre>
            <button
              onClick={() => { navigator.clipboard.writeText(data.controller_pubkey!); toast('Copied') }}
              className="absolute top-2 right-2 text-xs text-gray-400 hover:text-gray-600 bg-white border border-gray-200 rounded px-2 py-0.5"
            >
              Copy
            </button>
          </div>
        ) : (
          <p className="text-sm text-amber-700 bg-amber-50 border border-amber-200 rounded-lg p-3">
            No keypair generated yet. Save settings once to generate the controller keypair.
          </p>
        )}
      </div>

      <div className="flex items-center gap-3">
        <div className="h-px flex-1 bg-gray-200" />
        <span className="text-xs font-semibold text-gray-400 uppercase tracking-wide">Optional / Advanced</span>
        <div className="h-px flex-1 bg-gray-200" />
      </div>

      {/* Playbooks directory */}
      <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-6 space-y-4">
        <div>
          <h2 className="text-base font-semibold text-gray-900">Playbooks Directory</h2>
          <p className="text-sm text-gray-500 mt-1">Override the directory kri scans for Ansible playbooks and roles.</p>
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Path to playbooks &amp; roles</label>
          <input type="text" value={playbooksDir} onChange={(e) => setPlaybooksDir(e.target.value)}
            placeholder="/home/user/my-playbooks  (default: <repo>/playbooks)"
            className={monoInputClass} />
          <p className="text-xs text-gray-400 mt-1">
            Roles must be in a <code>roles/</code> subdirectory. Leave blank to use the built-in <code>playbooks/</code> folder.
          </p>
        </div>
      </div>

      {/* Pillar directory */}
      <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-6 space-y-4">
        <div>
          <h2 className="text-base font-semibold text-gray-900">Salt Pillar Directory</h2>
          <p className="text-sm text-gray-500 mt-1">
            kri writes a per-node <code className="text-xs bg-gray-100 px-1 rounded">&lt;minion_id&gt;.sls</code> file here before every bootstrap. The Salt master reads from this directory to provide each minion with its ingest URL and node token.
          </p>
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Path to Salt pillar directory</label>
          <input type="text" value={pillarDir} onChange={(e) => setPillarDir(e.target.value)}
            placeholder="/srv/salt/pillar  (default)"
            className={monoInputClass} />
          <p className="text-xs text-gray-400 mt-1">Must be writable by the kri process.</p>
        </div>
      </div>

      {/* External Ansible endpoint */}
      <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-6 space-y-4">
        <div>
          <h2 className="text-base font-semibold text-gray-900">External Ansible Endpoint</h2>
          <p className="text-sm text-gray-500 mt-1">
            Configure an AWX or Ansible Tower endpoint. When set, kri sends playbook jobs to this endpoint instead of running <code className="text-xs bg-gray-100 px-1 rounded">ansible-runner</code> locally.
          </p>
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Endpoint URL</label>
          <input type="text" value={ansibleEndpoint} onChange={(e) => setAnsibleEndpoint(e.target.value)}
            placeholder="https://awx.example.com" className={inputClass} />
          <p className="text-xs text-gray-400 mt-1">Leave blank to use local ansible-runner.</p>
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">
            API Token <span className="ml-2 text-xs font-normal text-gray-400">(stored encrypted)</span>
          </label>
          <input type="password" value={ansibleToken} onChange={(e) => setAnsibleToken(e.target.value)}
            placeholder="Leave blank to keep existing" className={inputClass} />
        </div>
      </div>

      <div className="flex justify-end">
        <button
          onClick={() => saveMutation.mutate()}
          disabled={saveMutation.isPending}
          className="px-6 py-2.5 bg-brand-600 text-white rounded-lg font-medium hover:bg-brand-700 disabled:opacity-50 shadow-sm"
        >
          {saveMutation.isPending ? 'Saving…' : 'Save Settings'}
        </button>
      </div>

      <div className="flex items-center gap-3">
        <div className="h-px flex-1 bg-gray-200" />
        <span className="text-xs font-semibold text-gray-400 uppercase tracking-wide">Playbook Sources</span>
        <div className="h-px flex-1 bg-gray-200" />
      </div>

      <PlaybookSourcesSection />
    </div>
  )
}

// ---------------------------------------------------------------------------
// Playbook Sources sub-section (self-contained, uses its own queries)
// ---------------------------------------------------------------------------

function TypeBadge({ type }: { type: string }) {
  if (type === 'git') {
    return (
      <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-purple-100 text-purple-700">
        git
      </span>
    )
  }
  return (
    <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-blue-100 text-blue-700">
      local
    </span>
  )
}

function PlaybookSourcesSection() {
  const qc = useQueryClient()
  const toast = useToastStore((s) => s.add)

  // Form state — add local
  const [showAddLocal, setShowAddLocal] = useState(false)
  const [localPath, setLocalPath] = useState('')
  const [localLabel, setLocalLabel] = useState('')

  // Form state — add git
  const [showAddGit, setShowAddGit] = useState(false)
  const [gitUrl, setGitUrl] = useState('')
  const [gitBranch, setGitBranch] = useState('main')
  const [gitLabel, setGitLabel] = useState('')

  // CSV import
  const [showCsv, setShowCsv] = useState(false)
  const [csvText, setCsvText] = useState('')

  const { data: sources = [], isLoading } = useQuery({
    queryKey: ['playbook-sources'],
    queryFn: playbookSourcesApi.list,
  })

  const addMutation = useMutation({
    mutationFn: playbookSourcesApi.add,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['playbook-sources'] })
      qc.invalidateQueries({ queryKey: ['playbooks'] })
      toast('Source added')
      setLocalPath(''); setLocalLabel(''); setShowAddLocal(false)
      setGitUrl(''); setGitBranch('main'); setGitLabel(''); setShowAddGit(false)
    },
    onError: (e: Error) => toast(e.message, 'error'),
  })

  const removeMutation = useMutation({
    mutationFn: playbookSourcesApi.remove,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['playbook-sources'] })
      qc.invalidateQueries({ queryKey: ['playbooks'] })
      toast('Source removed')
    },
    onError: (e: Error) => toast(e.message, 'error'),
  })

  const syncMutation = useMutation({
    mutationFn: playbookSourcesApi.sync,
    onSuccess: (data) => {
      qc.invalidateQueries({ queryKey: ['playbooks'] })
      const ok = data.results.filter((r) => r.status === 'ok').length
      const err = data.results.filter((r) => r.status === 'error').length
      toast(err > 0 ? `Sync: ${ok} ok, ${err} failed` : `Synced ${ok} git source(s)`, err > 0 ? 'error' : undefined)
    },
    onError: (e: Error) => toast(e.message, 'error'),
  })

  const importMutation = useMutation({
    mutationFn: (csv: string) => playbookSourcesApi.importCsv(csv),
    onSuccess: (data) => {
      qc.invalidateQueries({ queryKey: ['playbook-sources'] })
      qc.invalidateQueries({ queryKey: ['playbooks'] })
      toast(`Imported ${data.added} source(s)`)
      setCsvText(''); setShowCsv(false)
    },
    onError: (e: Error) => toast(e.message, 'error'),
  })

  function handleAddLocal() {
    if (!localPath.trim()) return
    addMutation.mutate({ type: 'local', path: localPath.trim(), label: localLabel.trim() || undefined })
  }

  function handleAddGit() {
    if (!gitUrl.trim()) return
    addMutation.mutate({ type: 'git', url: gitUrl.trim(), branch: gitBranch.trim() || 'main', label: gitLabel.trim() || undefined })
  }

  const inputClass = 'w-full px-3 py-2 border border-gray-300 rounded-lg text-sm text-gray-900 focus:outline-none focus:border-brand-600 font-mono'
  const btnPrimary = 'px-4 py-2 bg-brand-600 text-white text-sm rounded-lg font-medium hover:bg-brand-700 disabled:opacity-50'
  const btnSecondary = 'px-4 py-2 bg-white border border-gray-300 text-gray-700 text-sm rounded-lg font-medium hover:bg-gray-50'

  return (
    <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-6 space-y-5">
      <div className="flex items-start justify-between">
        <div>
          <h2 className="text-base font-semibold text-gray-900">Playbook Sources</h2>
          <p className="text-sm text-gray-500 mt-0.5">
            Additional directories and git repositories to scan for playbooks.
            The built-in <code className="text-xs bg-gray-100 px-1 rounded">playbooks/</code> directory is always included.
          </p>
        </div>
        {(sources as PlaybookSource[]).some((s) => s.type === 'git') && (
          <button
            onClick={() => syncMutation.mutate()}
            disabled={syncMutation.isPending}
            className={btnSecondary}
            title="Pull latest changes for all git sources"
          >
            {syncMutation.isPending ? 'Syncing…' : 'Sync All'}
          </button>
        )}
      </div>

      {/* Built-in source (read-only) */}
      <div className="flex items-center gap-3 px-3 py-2.5 bg-gray-50 border border-gray-200 rounded-lg">
        <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-gray-200 text-gray-600">built-in</span>
        <span className="text-sm font-mono text-gray-700 flex-1">playbooks/</span>
        <span className="text-xs text-gray-400 italic">always active, cannot be removed</span>
      </div>

      {/* Configured sources */}
      {isLoading ? (
        <p className="text-sm text-gray-400">Loading…</p>
      ) : (sources as PlaybookSource[]).length === 0 ? (
        <p className="text-sm text-gray-400">No additional sources configured.</p>
      ) : (
        <ul className="space-y-2">
          {(sources as PlaybookSource[]).map((src) => (
            <li key={src.index} className="flex items-center gap-3 px-3 py-2.5 border border-gray-200 rounded-lg">
              <TypeBadge type={src.type} />
              <span className="text-sm font-mono text-gray-800 flex-1 truncate">
                {src.type === 'local' ? src.path : src.url}
              </span>
              {src.type === 'git' && src.branch && (
                <span className="text-xs text-gray-400">branch: {src.branch}</span>
              )}
              {src.label && (
                <span className="text-xs text-gray-500 italic">{src.label}</span>
              )}
              <button
                onClick={() => removeMutation.mutate(src.index)}
                disabled={removeMutation.isPending}
                className="ml-auto text-gray-400 hover:text-red-500 transition-colors disabled:opacity-50"
                title="Remove source"
              >
                <svg xmlns="http://www.w3.org/2000/svg" className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                </svg>
              </button>
            </li>
          ))}
        </ul>
      )}

      {/* Action buttons */}
      <div className="flex flex-wrap gap-2">
        <button onClick={() => { setShowAddLocal(!showAddLocal); setShowAddGit(false); setShowCsv(false) }} className={btnSecondary}>
          + Add Local Directory
        </button>
        <button onClick={() => { setShowAddGit(!showAddGit); setShowAddLocal(false); setShowCsv(false) }} className={btnSecondary}>
          + Add Git Repository
        </button>
        <button onClick={() => { setShowCsv(!showCsv); setShowAddLocal(false); setShowAddGit(false) }} className={btnSecondary}>
          CSV Import
        </button>
      </div>

      {/* Add local form */}
      {showAddLocal && (
        <div className="border border-blue-200 bg-blue-50 rounded-lg p-4 space-y-3">
          <h3 className="text-sm font-semibold text-blue-900">Add Local Directory</h3>
          <div>
            <label className="block text-xs font-medium text-gray-700 mb-1">Absolute path</label>
            <input type="text" value={localPath} onChange={(e) => setLocalPath(e.target.value)}
              placeholder="/opt/custom-playbooks"
              className={inputClass} />
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-700 mb-1">Label (optional)</label>
            <input type="text" value={localLabel} onChange={(e) => setLocalLabel(e.target.value)}
              placeholder="Custom Playbooks"
              className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm text-gray-900 focus:outline-none focus:border-brand-600" />
          </div>
          <div className="flex gap-2">
            <button onClick={handleAddLocal} disabled={!localPath.trim() || addMutation.isPending} className={btnPrimary}>
              {addMutation.isPending ? 'Adding…' : 'Add'}
            </button>
            <button onClick={() => setShowAddLocal(false)} className={btnSecondary}>Cancel</button>
          </div>
        </div>
      )}

      {/* Add git form */}
      {showAddGit && (
        <div className="border border-purple-200 bg-purple-50 rounded-lg p-4 space-y-3">
          <h3 className="text-sm font-semibold text-purple-900">Add Git Repository</h3>
          <div>
            <label className="block text-xs font-medium text-gray-700 mb-1">Repository URL</label>
            <input type="text" value={gitUrl} onChange={(e) => setGitUrl(e.target.value)}
              placeholder="https://github.com/org/playbooks.git"
              className={inputClass} />
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-700 mb-1">Branch</label>
            <input type="text" value={gitBranch} onChange={(e) => setGitBranch(e.target.value)}
              placeholder="main"
              className={inputClass} />
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-700 mb-1">Label (optional)</label>
            <input type="text" value={gitLabel} onChange={(e) => setGitLabel(e.target.value)}
              placeholder="Org Playbooks"
              className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm text-gray-900 focus:outline-none focus:border-brand-600" />
          </div>
          <p className="text-xs text-gray-500">
            The repository will be cloned to <code className="bg-white px-1 rounded">/tmp/kri-git/&lt;repo-name&gt;</code> on first use.
          </p>
          <div className="flex gap-2">
            <button onClick={handleAddGit} disabled={!gitUrl.trim() || addMutation.isPending} className={btnPrimary}>
              {addMutation.isPending ? 'Adding…' : 'Add'}
            </button>
            <button onClick={() => setShowAddGit(false)} className={btnSecondary}>Cancel</button>
          </div>
        </div>
      )}

      {/* CSV import */}
      {showCsv && (
        <div className="border border-gray-200 bg-gray-50 rounded-lg p-4 space-y-3">
          <h3 className="text-sm font-semibold text-gray-900">CSV Bulk Import</h3>
          <p className="text-xs text-gray-500">
            One entry per line: <code className="bg-white px-1 rounded">type, path/url, branch (git only), label</code>
            <br />Lines starting with <code className="bg-white px-1 rounded">#</code> are ignored.
          </p>
          <div className="text-xs text-gray-400 font-mono bg-white border border-gray-200 rounded p-2 space-y-0.5">
            <div># type, path/url, branch, label</div>
            <div>local, /opt/custom-playbooks, , Custom Playbooks</div>
            <div>git, https://github.com/org/plays.git, main, Org Playbooks</div>
          </div>
          <textarea
            value={csvText}
            onChange={(e) => setCsvText(e.target.value)}
            rows={6}
            placeholder="local, /opt/custom-playbooks, , Custom Playbooks&#10;git, https://github.com/org/plays.git, main, Org Playbooks"
            className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm font-mono text-gray-900 focus:outline-none focus:border-brand-600 resize-y"
          />
          <div className="flex gap-2">
            <button
              onClick={() => importMutation.mutate(csvText)}
              disabled={!csvText.trim() || importMutation.isPending}
              className={btnPrimary}
            >
              {importMutation.isPending ? 'Importing…' : 'Import'}
            </button>
            <button onClick={() => setShowCsv(false)} className={btnSecondary}>Cancel</button>
          </div>
        </div>
      )}
    </div>
  )
}
