import { useState } from 'react'
import { useParams, Link } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { groupsApi, type GroupCredentials } from '../api/groups'
import { fleetApi } from '../api/fleet'
import { groupSecretsApi } from '../api/groupSecrets'
import { StatusBadge } from '../components/StatusBadge'
import { DriftBadge } from '../components/DriftBadge'
import { Skeleton } from '../components/Skeleton'
import { ErrorState } from '../components/ErrorState'
import { Pagination } from '../components/Pagination'
import { ConfirmDialog } from '../components/ConfirmDialog'
import { useToastStore } from '../stores/toastStore'
import { formatDistanceToNow } from 'date-fns'

type GroupTab = 'Members' | 'Drift' | 'SSH' | 'Secrets'

export function GroupDetail() {
  const { groupId } = useParams<{ groupId: string }>()
  const [page, setPage] = useState(1)
  const [showAddNode, setShowAddNode] = useState(false)
  const [addNodeId, setAddNodeId] = useState('')
  const [activeTab, setActiveTab] = useState<GroupTab>('Members')
  const qc = useQueryClient()
  const toast = useToastStore((s) => s.add)

  // SSH credentials form state
  const [sshUsername, setSshUsername] = useState('')
  const [sshPassword, setSshPassword] = useState('')
  const [sshAuthMode, setSshAuthMode] = useState<'password' | 'key'>('password')
  const [sshKey, setSshKey] = useState('')
  const [sessionMaxMins, setSessionMaxMins] = useState('')
  const [sessionRetentionDays, setSessionRetentionDays] = useState('')
  const [credFormInit, setCredFormInit] = useState(false)
  // Secrets tab state
  const [secretKey, setSecretKey] = useState('')
  const [secretValue, setSecretValue] = useState('')
  const [secretDesc, setSecretDesc] = useState('')
  const [secretShowValue, setSecretShowValue] = useState(false)
  // Confirm dialog state
  const [deleteSecretConfirm, setDeleteSecretConfirm] = useState<string | null>(null)
  const [removeMemberConfirm, setRemoveMemberConfirm] = useState<string | null>(null)

  const { data: group, isLoading: gLoading, isError: gError } = useQuery({
    queryKey: ['group', groupId],
    queryFn: () => groupsApi.get(groupId!),
    enabled: !!groupId,
  })

  const { data: members, isLoading: mLoading } = useQuery({
    queryKey: ['group-members', groupId, page],
    queryFn: () => groupsApi.members(groupId!, { page, per_page: 25 }),
    enabled: !!groupId,
    staleTime: 30_000,
  })

  const { data: allMembers, isLoading: allMembersLoading } = useQuery({
    queryKey: ['group-members-all', groupId],
    queryFn: () => groupsApi.members(groupId!, { page: 1, per_page: 200 }),
    enabled: !!groupId && activeTab === 'Drift',
    staleTime: 60_000,
  })

  const { data: creds, isLoading: credsLoading } = useQuery<GroupCredentials>({
    queryKey: ['group-credentials', groupId],
    queryFn: () => groupsApi.getCredentials(groupId!),
    enabled: !!groupId,
    staleTime: 60_000,
  })

  // Initialise form from fetched creds (run once when data arrives)
  if (creds && !credFormInit) {
    setSshUsername(creds.ssh_username ?? '')
    setSshAuthMode((creds.ssh_auth_mode as 'password' | 'key') ?? 'password')
    setSessionMaxMins(String(creds.session_max_mins ?? 60))
    setSessionRetentionDays(String(creds.session_retention_days ?? 30))
    setCredFormInit(true)
  }

  // For the add-node selector: fetch all nodes to pick from
  const { data: allNodes } = useQuery({
    queryKey: ['nodes-for-group'],
    queryFn: () => fleetApi.nodes({ per_page: 200 }),
    enabled: showAddNode && group?.type === 'static',
    staleTime: 60_000,
  })

  const addMutation = useMutation({
    mutationFn: (nodeId: string) => groupsApi.addMember(groupId!, nodeId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['group-members', groupId] })
      qc.invalidateQueries({ queryKey: ['group', groupId] })
      setAddNodeId('')
      setShowAddNode(false)
      toast('Node added to group')
    },
    onError: (e: Error) => toast(e.message, 'error'),
  })

  const removeMutation = useMutation({
    mutationFn: (nodeId: string) => groupsApi.removeMember(groupId!, nodeId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['group-members', groupId] })
      qc.invalidateQueries({ queryKey: ['group', groupId] })
      toast('Node removed from group')
    },
    onError: (e: Error) => toast(e.message, 'error'),
  })

  const credsMutation = useMutation({
    mutationFn: () =>
      groupsApi.updateCredentials(groupId!, {
        ssh_username: sshUsername || null,
        ssh_password: sshPassword || null,
        ssh_auth_mode: sshAuthMode,
        ssh_key: sshKey || null,
        session_max_mins: sessionMaxMins ? parseInt(sessionMaxMins) : null,
        session_retention_days: sessionRetentionDays ? parseInt(sessionRetentionDays) : null,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['group-credentials', groupId] })
      setSshPassword('')
      setSshKey('')
      toast('SSH credentials saved')
    },
    onError: (e: Error) => toast(e.message, 'error'),
  })

  const { data: groupSecrets } = useQuery({
    queryKey: ['group-secrets', groupId],
    queryFn: () => groupSecretsApi.list(groupId!),
    staleTime: 30_000,
    enabled: !!groupId && activeTab === 'Secrets',
  })

  const addGroupSecretMutation = useMutation({
    mutationFn: () =>
      groupSecretsApi.upsert(groupId!, secretKey.trim(), secretValue, secretDesc.trim() || undefined),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['group-secrets', groupId] })
      setSecretKey('')
      setSecretValue('')
      setSecretDesc('')
      toast('Secret saved')
    },
    onError: (e: Error) => toast(e.message, 'error'),
  })

  const deleteGroupSecretMutation = useMutation({
    mutationFn: (key: string) => groupSecretsApi.delete(groupId!, key),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['group-secrets', groupId] })
      toast('Secret deleted')
    },
    onError: (e: Error) => toast(e.message, 'error'),
  })

  if (gLoading) return <Skeleton rows={4} />
  if (gError || !group) return <ErrorState message="Group not found" />

  const isStatic = group.type === 'static'
  const memberIds = new Set(members?.items.map((n) => n.id) ?? [])
  const nonMembers = allNodes?.items.filter((n) => !memberIds.has(n.id)) ?? []

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center gap-3">
        <Link to="/groups" className="text-sm text-brand-600 hover:underline">← Groups</Link>
        <span className="text-gray-400">/</span>
        <h1 className="text-2xl font-bold text-gray-900">{group.name}</h1>
        <span
          title={group.type === 'dynamic'
            ? 'Dynamic group: membership is resolved automatically from a predicate. Nodes cannot be added or removed manually.'
            : 'Static group: add and remove nodes manually using the controls below.'}
          className={`cursor-help text-xs px-2 py-0.5 rounded font-medium ${
            group.type === 'dynamic'
              ? 'bg-purple-100 text-purple-800 border border-purple-200'
              : 'bg-gray-100 text-gray-700 border border-gray-200'
          }`}
        >
          {group.type} ℹ
        </span>
      </div>

      {group.description && <p className="text-gray-600">{group.description}</p>}

      {/* Warning: no SSH credentials configured */}
      {!credsLoading && !creds?.ssh_username && (
        <div className="bg-amber-50 border border-amber-200 rounded-xl p-4 flex items-start gap-3">
          <span className="text-amber-500 text-lg mt-0.5">⚠</span>
          <div>
            <p className="text-sm font-semibold text-amber-800">No SSH credentials configured</p>
            <p className="text-sm text-amber-700 mt-0.5">
              Nodes in this group cannot be bootstrapped until SSH credentials are set below.
            </p>
          </div>
        </div>
      )}

      {group.predicate && (
        <div className="bg-gray-50 rounded-lg border border-gray-200 p-4">
          <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">Predicate</p>
          <pre className="text-xs font-mono text-gray-700">{JSON.stringify(group.predicate, null, 2)}</pre>
          <p className="text-xs text-gray-400 mt-2">
            Members are resolved dynamically from this predicate — manual add/remove is not supported.
          </p>
        </div>
      )}

      {/* Tab bar */}
      <div className="flex border-b border-gray-200">
        {(['Members', 'Drift', 'SSH', 'Secrets'] as GroupTab[]).map(tab => (
          <button key={tab} onClick={() => setActiveTab(tab)}
            className={`px-4 py-2.5 text-sm font-medium border-b-2 -mb-px transition-colors ${
              activeTab === tab
                ? 'border-brand-600 text-brand-700'
                : 'border-transparent text-gray-500 hover:text-gray-700'
            }`}
          >
            {tab}
          </button>
        ))}
      </div>

      {/* Drift tab */}
      {activeTab === 'Drift' && (
        <div className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">
          {allMembersLoading ? (
            <Skeleton rows={5} />
          ) : (() => {
            const driftNodes = [...(allMembers?.items ?? [])].sort((a, b) => (b.drift_score ?? 0) - (a.drift_score ?? 0))
            const drifted = driftNodes.filter(n => (n.drift_score ?? 0) > 5)
            return (
              <>
                <div className="px-4 py-3 border-b border-gray-200 flex items-center justify-between">
                  <span className="text-sm font-semibold text-gray-700">Drift Summary</span>
                  <span className="text-xs text-gray-500">
                    {drifted.length} of {driftNodes.length} nodes drifted (score &gt; 5)
                  </span>
                </div>
                {driftNodes.length === 0 ? (
                  <div className="px-4 py-12 text-center text-gray-400 text-sm">No members to show drift for.</div>
                ) : (
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="bg-gray-50 border-b border-gray-200 text-left text-xs font-semibold text-gray-500 uppercase tracking-wide">
                        <th className="px-4 py-3">Node</th>
                        <th className="px-4 py-3">Drift Score</th>
                        <th className="px-4 py-3">Severity</th>
                        <th className="px-4 py-3">Last Seen</th>
                        <th className="px-4 py-3 w-24"></th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-gray-100">
                      {driftNodes.map(n => (
                        <tr key={n.id} className="hover:bg-gray-50 transition-colors">
                          <td className="px-4 py-3">
                            <Link to={`/nodes/${n.id}`} className="text-brand-600 hover:underline font-medium">
                              {n.hostname ?? n.minion_id}
                            </Link>
                          </td>
                          <td className="px-4 py-3 font-mono text-sm text-gray-700">{n.drift_score ?? 0}</td>
                          <td className="px-4 py-3"><DriftBadge score={n.drift_score} /></td>
                          <td className="px-4 py-3 text-gray-400 text-xs">
                            {n.last_seen_at ? formatDistanceToNow(new Date(n.last_seen_at), { addSuffix: true }) : '—'}
                          </td>
                          <td className="px-4 py-3 text-right">
                            <Link to={`/nodes/${n.id}`} className="text-xs text-brand-600 hover:text-brand-700 font-medium">
                              View Drift →
                            </Link>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </>
            )
          })()}
        </div>
      )}

      {/* SSH Credentials card */}
      {activeTab === 'SSH' && <div className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">
        <div className="px-4 py-3 border-b border-gray-200">
          <p className="text-sm font-semibold text-gray-700">SSH Credentials</p>
          <p className="text-xs text-gray-400 mt-0.5">
            All nodes in this group inherit these credentials unless overridden at the node level.
          </p>
        </div>

        {credsLoading ? (
          <Skeleton rows={3} />
        ) : (
          <div className="px-4 py-5 space-y-4">
            {/* Current status */}
            {creds && (
              <div className="flex flex-wrap gap-3 text-xs">
                <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full font-medium border ${
                  creds.ssh_username
                    ? 'bg-emerald-50 text-emerald-700 border-emerald-200'
                    : 'bg-gray-100 text-gray-500 border-gray-200'
                }`}>
                  {creds.ssh_username ? `User: ${creds.ssh_username}` : 'No username set'}
                </span>
                <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full font-medium border ${
                  creds.has_ssh_password
                    ? 'bg-emerald-50 text-emerald-700 border-emerald-200'
                    : 'bg-gray-100 text-gray-500 border-gray-200'
                }`}>
                  Password: {creds.has_ssh_password ? 'configured' : 'not set'}
                </span>
                <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full font-medium border ${
                  creds.has_ssh_key
                    ? 'bg-emerald-50 text-emerald-700 border-emerald-200'
                    : 'bg-gray-100 text-gray-500 border-gray-200'
                }`}>
                  SSH Key: {creds.has_ssh_key ? 'configured' : 'not set'}
                </span>
              </div>
            )}

            {/* Auth mode toggle */}
            <div className="space-y-1">
              <p className="text-sm font-medium text-gray-700">Authentication Mode</p>
              <div className="flex gap-4">
                {(['password', 'key'] as const).map((mode) => (
                  <label key={mode} className="flex items-center gap-2 text-sm cursor-pointer">
                    <input
                      type="radio"
                      name="groupAuthMode"
                      value={mode}
                      checked={sshAuthMode === mode}
                      onChange={() => setSshAuthMode(mode)}
                      className="accent-brand-600"
                    />
                    {mode === 'password' ? 'Password auth' : 'SSH key auth'}
                  </label>
                ))}
              </div>
            </div>

            {/* Username */}
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">SSH Username</label>
              <input
                value={sshUsername}
                onChange={(e) => setSshUsername(e.target.value)}
                placeholder="admin"
                className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm text-gray-900 focus:outline-none focus:border-brand-600"
              />
            </div>

            {/* Password or Key */}
            {sshAuthMode === 'password' ? (
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Password{' '}
                  {creds?.has_ssh_password && (
                    <span className="text-gray-400 font-normal">(saved — leave blank to keep)</span>
                  )}
                </label>
                <input
                  type="password"
                  value={sshPassword}
                  onChange={(e) => setSshPassword(e.target.value)}
                  placeholder={creds?.has_ssh_password ? '••••••••' : 'Enter password'}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm text-gray-900 focus:outline-none focus:border-brand-600"
                />
              </div>
            ) : (
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Private Key{' '}
                  {creds?.has_ssh_key && (
                    <span className="text-gray-400 font-normal">(saved — paste to replace)</span>
                  )}
                </label>
                <textarea
                  rows={6}
                  value={sshKey}
                  onChange={(e) => setSshKey(e.target.value)}
                  placeholder={'-----BEGIN OPENSSH PRIVATE KEY-----\n...'}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm font-mono text-gray-900 focus:outline-none focus:border-brand-600 resize-none"
                />
                <p className="text-xs text-gray-400 mt-1">
                  Paste the private key. The public key will be authorized on the node automatically during bootstrap.
                </p>
              </div>
            )}

            {/* Session settings */}
            <div className="border-t border-gray-100 pt-4 space-y-3">
              <p className="text-sm font-semibold text-gray-700">Session Settings</p>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">
                    Max Session Duration (minutes)
                  </label>
                  <input
                    type="number"
                    min="1"
                    value={sessionMaxMins}
                    onChange={(e) => setSessionMaxMins(e.target.value)}
                    placeholder="60"
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm text-gray-900 focus:outline-none focus:border-brand-600"
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">
                    Log Retention (days)
                  </label>
                  <input
                    type="number"
                    min="1"
                    value={sessionRetentionDays}
                    onChange={(e) => setSessionRetentionDays(e.target.value)}
                    placeholder="30"
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm text-gray-900 focus:outline-none focus:border-brand-600"
                  />
                </div>
              </div>
            </div>

            {/* Save button */}
            <div className="flex justify-end pt-2">
              <button
                disabled={credsMutation.isPending}
                onClick={() => credsMutation.mutate()}
                className="px-5 py-2 bg-brand-600 text-white text-sm font-medium rounded-lg hover:bg-brand-700 disabled:opacity-50"
              >
                {credsMutation.isPending ? 'Saving…' : 'Save Credentials'}
              </button>
            </div>
          </div>
        )}
      </div>}

      {/* Secrets section */}
      {activeTab === 'Secrets' && (
        <div className="space-y-4">
          <div className="bg-amber-50 border border-amber-200 rounded-xl p-4 flex items-start gap-3">
            <span className="text-amber-500 text-lg mt-0.5">ℹ</span>
            <p className="text-sm text-amber-800">
              These secrets are available to all group members as{' '}
              <code className="font-mono bg-amber-100 px-1 rounded">{'{{ pillar[\'key\'] }}'}</code>{' '}
              in Salt states.
            </p>
          </div>

          <div className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">
            <div className="px-4 py-3 border-b border-gray-200">
              <p className="text-sm font-semibold text-gray-700">Group Secrets</p>
              <p className="text-xs text-gray-400 mt-0.5">Values are write-only and never displayed.</p>
            </div>
            {!groupSecrets || groupSecrets.length === 0 ? (
              <div className="px-4 py-8 text-center text-gray-400 text-sm">No secrets stored for this group.</div>
            ) : (
              <table className="w-full text-sm">
                <thead>
                  <tr className="bg-gray-50 border-b border-gray-200 text-left text-xs font-semibold text-gray-500 uppercase tracking-wide">
                    <th className="px-4 py-3">Key</th>
                    <th className="px-4 py-3">Description</th>
                    <th className="px-4 py-3">Last Updated</th>
                    <th className="px-4 py-3 w-20"></th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {groupSecrets.map((s) => (
                    <tr key={s.key} className="hover:bg-gray-50">
                      <td className="px-4 py-3 font-mono font-medium text-gray-900">{s.key}</td>
                      <td className="px-4 py-3 text-gray-500 text-xs">{s.description ?? '—'}</td>
                      <td className="px-4 py-3 text-gray-400 text-xs">
                        {new Date(s.updated_at).toLocaleString('en-IN', { timeZone: 'Asia/Kolkata', day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false })} IST
                      </td>
                      <td className="px-4 py-3 text-right">
                        <button
                          onClick={() => setDeleteSecretConfirm(s.key)}
                          disabled={deleteGroupSecretMutation.isPending}
                          className="text-xs text-red-600 hover:text-red-700 font-medium disabled:opacity-50"
                        >
                          Delete
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>

          <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-4 space-y-3">
            <p className="text-sm font-semibold text-gray-700">Add / Update Secret</p>
            <form
              onSubmit={(e) => { e.preventDefault(); addGroupSecretMutation.mutate() }}
              className="space-y-3"
            >
              <div className="flex gap-3 flex-wrap">
                <div className="flex-1 min-w-32">
                  <label className="block text-xs text-gray-500 mb-1">Key</label>
                  <input
                    value={secretKey}
                    onChange={(e) => setSecretKey(e.target.value)}
                    placeholder="e.g. jenkins_url"
                    required
                    className="w-full text-sm border border-gray-300 rounded px-2 py-1.5 font-mono focus:outline-none focus:ring-2 focus:ring-brand-400"
                  />
                </div>
                <div className="flex-1 min-w-40">
                  <label className="block text-xs text-gray-500 mb-1">Value</label>
                  <div className="relative">
                    <input
                      type={secretShowValue ? 'text' : 'password'}
                      value={secretValue}
                      onChange={(e) => setSecretValue(e.target.value)}
                      placeholder="Secret value"
                      required
                      className="w-full text-sm border border-gray-300 rounded px-2 py-1.5 pr-16 focus:outline-none focus:ring-2 focus:ring-brand-400"
                    />
                    <button
                      type="button"
                      onClick={() => setSecretShowValue((v) => !v)}
                      className="absolute right-2 top-1/2 -translate-y-1/2 text-xs text-gray-400 hover:text-gray-600"
                    >
                      {secretShowValue ? 'Hide' : 'Show'}
                    </button>
                  </div>
                </div>
                <div className="flex-1 min-w-32">
                  <label className="block text-xs text-gray-500 mb-1">Description (optional)</label>
                  <input
                    value={secretDesc}
                    onChange={(e) => setSecretDesc(e.target.value)}
                    placeholder="Brief description"
                    className="w-full text-sm border border-gray-300 rounded px-2 py-1.5 focus:outline-none focus:ring-2 focus:ring-brand-400"
                  />
                </div>
              </div>
              <div className="flex justify-end">
                <button
                  type="submit"
                  disabled={addGroupSecretMutation.isPending || !secretKey.trim() || !secretValue}
                  className="px-4 py-2 bg-brand-600 text-white text-sm rounded-lg hover:bg-brand-700 disabled:opacity-50 font-medium"
                >
                  {addGroupSecretMutation.isPending ? 'Saving…' : 'Save Secret'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Members table */}
      {activeTab === 'Members' && <div className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">
        <div className="px-4 py-3 border-b border-gray-200 flex items-center justify-between">
          <span className="text-sm font-semibold text-gray-700">
            Members <span className="text-gray-400 font-normal">({group.member_count})</span>
          </span>
          {isStatic && (
            <button
              onClick={() => setShowAddNode(!showAddNode)}
              className="text-sm text-brand-600 hover:text-brand-700 font-medium"
            >
              {showAddNode ? 'Cancel' : '+ Add node'}
            </button>
          )}
        </div>

        {/* Add node selector (static groups only) */}
        {showAddNode && isStatic && (
          <div className="px-4 py-3 bg-brand-50 border-b border-brand-100 flex items-center gap-3">
            <select
              value={addNodeId}
              onChange={(e) => setAddNodeId(e.target.value)}
              className="flex-1 text-sm bg-white border border-gray-300 text-gray-900 rounded-lg px-3 py-1.5 focus:outline-none focus:border-brand-600"
            >
              <option value="">Select a node…</option>
              {nonMembers.map((n) => (
                <option key={n.id} value={n.id}>
                  {n.hostname ?? n.minion_id} — {n.ip_address ?? 'unknown IP'}
                </option>
              ))}
            </select>
            <button
              disabled={!addNodeId || addMutation.isPending}
              onClick={() => addMutation.mutate(addNodeId)}
              className="px-4 py-1.5 bg-brand-600 text-white text-sm font-medium rounded-lg hover:bg-brand-700 disabled:opacity-50"
            >
              {addMutation.isPending ? 'Adding…' : 'Add'}
            </button>
          </div>
        )}

        {mLoading ? (
          <Skeleton rows={5} />
        ) : members?.items.length === 0 ? (
          <div className="px-4 py-12 text-center text-gray-400 text-sm">
            {isStatic ? 'No members yet. Click "+ Add node" to add one.' : 'No nodes match this predicate.'}
          </div>
        ) : (
          <>
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-gray-50 border-b border-gray-200 text-left text-xs font-semibold text-gray-500 uppercase tracking-wide">
                  <th className="px-4 py-3">Hostname</th>
                  <th className="px-4 py-3">Status</th>
                  <th className="px-4 py-3">Drift</th>
                  <th className="px-4 py-3">OS</th>
                  {isStatic && <th className="px-4 py-3 w-16"></th>}
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {members?.items.map((n) => (
                  <tr key={n.id} className="hover:bg-gray-50 transition-colors">
                    <td className="px-4 py-3">
                      <Link to={`/nodes/${n.id}`} className="text-brand-600 hover:underline font-medium">
                        {n.hostname ?? n.minion_id}
                      </Link>
                      {n.ip_address && (
                        <p className="text-xs text-gray-400 mt-0.5 font-mono">{n.ip_address}</p>
                      )}
                    </td>
                    <td className="px-4 py-3"><StatusBadge status={n.status} /></td>
                    <td className="px-4 py-3"><DriftBadge score={n.drift_score} /></td>
                    <td className="px-4 py-3 text-gray-600 text-xs">{n.os_version ?? '—'}</td>
                    {isStatic && (
                      <td className="px-4 py-3 text-right">
                        <button
                          onClick={() => setRemoveMemberConfirm(n.id)}
                          disabled={removeMutation.isPending}
                          className="text-xs text-red-500 hover:text-red-700 font-medium disabled:opacity-50"
                          title="Remove from group"
                        >
                          Remove
                        </button>
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
            {members && (
              <Pagination page={page} total={members.total} perPage={members.per_page} onPage={setPage} />
            )}
          </>
        )}
      </div>}

      {deleteSecretConfirm && (
        <ConfirmDialog
          title="Delete secret?"
          message="This secret will be permanently deleted and cannot be recovered."
          confirmLabel="Delete"
          destructive
          onConfirm={() => { deleteGroupSecretMutation.mutate(deleteSecretConfirm); setDeleteSecretConfirm(null) }}
          onCancel={() => setDeleteSecretConfirm(null)}
        />
      )}

      {removeMemberConfirm && (
        <ConfirmDialog
          title="Remove node from group?"
          message="This node will be removed from the group. You can re-add it later."
          confirmLabel="Remove"
          destructive
          onConfirm={() => { removeMutation.mutate(removeMemberConfirm); setRemoveMemberConfirm(null) }}
          onCancel={() => setRemoveMemberConfirm(null)}
        />
      )}
    </div>
  )
}
