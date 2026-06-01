/**
 * MobileconfigManager — macOS configuration profile management panel.
 *
 * Features:
 * - Upload .mobileconfig files and store them in kri
 * - View per-profile compliance status across fleet nodes
 * - Deploy (install) or revoke (remove) profiles from nodes
 * - Delete profiles (admin only)
 */
import { useRef, useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { formatDistanceToNow } from 'date-fns'
import {
  mobileconfigApi,
  type MobileconfigProfile,
  type ProfileComplianceEntry,
} from '../api/mobileconfig'
import { fleetApi } from '../api/fleet'
import { useToastStore } from '../stores/toastStore'
import { useAuthStore } from '../stores/authStore'
import { Skeleton } from '../components/Skeleton'
import { ErrorState } from '../components/ErrorState'

// ─── Status badge ────────────────────────────────────────────────────────────

function StatusBadge({ status }: { status: string }) {
  const cls: Record<string, string> = {
    installed:     'bg-green-100 text-green-700 border border-green-200',
    not_installed: 'bg-red-100 text-red-700 border border-red-200',
    failed:        'bg-red-100 text-red-700 border border-red-200',
    pending:       'bg-yellow-100 text-yellow-700 border border-yellow-200',
    unknown:       'bg-gray-100 text-gray-600 border border-gray-200',
  }
  const label: Record<string, string> = {
    installed:     'Installed',
    not_installed: 'Not Installed',
    failed:        'Failed',
    pending:       'Pending',
    unknown:       'Unknown',
  }
  const resolved = cls[status] ?? cls.unknown
  return (
    <span className={`inline-block px-2 py-0.5 rounded text-xs font-medium ${resolved}`}>
      {label[status] ?? status}
    </span>
  )
}

// ─── Upload form ─────────────────────────────────────────────────────────────

function UploadForm({ onDone }: { onDone: () => void }) {
  const toast = useToastStore(s => s.add)
  const qc = useQueryClient()
  const fileRef = useRef<HTMLInputElement>(null)

  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [xml, setXml] = useState('')
  const [fileName, setFileName] = useState('')

  const createMut = useMutation({
    mutationFn: () =>
      mobileconfigApi.createProfile({ name, description: description || null, payload_xml: xml }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['mobileconfig-profiles'] })
      toast('Profile uploaded successfully', 'success')
      onDone()
    },
    onError: (e: Error) => toast(e.message, 'error'),
  })

  function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (!file) return
    const reader = new FileReader()
    reader.onload = ev => {
      const content = ev.target?.result as string
      setXml(content)
      setFileName(file.name)
      if (!name) setName(file.name.replace(/\.mobileconfig$/i, ''))
    }
    reader.readAsText(file)
  }

  return (
    <div className="space-y-3">
      <div>
        <label className="block text-xs font-medium text-gray-700 mb-1">
          Profile File <span className="text-red-500">*</span>
        </label>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => fileRef.current?.click()}
            className="px-3 py-1.5 text-sm border border-gray-300 rounded-lg hover:bg-gray-50 text-gray-700"
          >
            Choose .mobileconfig
          </button>
          {fileName && <span className="text-xs text-gray-500">{fileName}</span>}
        </div>
        <input
          ref={fileRef}
          type="file"
          accept=".mobileconfig"
          onChange={handleFileChange}
          className="hidden"
        />
      </div>

      <div>
        <label className="block text-xs font-medium text-gray-700 mb-1">
          Display Name <span className="text-red-500">*</span>
        </label>
        <input
          type="text"
          value={name}
          onChange={e => setName(e.target.value)}
          placeholder="e.g. Wi-Fi Corp Profile"
          className="w-full px-3 py-1.5 text-sm border border-gray-300 rounded-lg focus:outline-none focus:border-blue-500"
        />
      </div>

      <div>
        <label className="block text-xs font-medium text-gray-700 mb-1">Description</label>
        <input
          type="text"
          value={description}
          onChange={e => setDescription(e.target.value)}
          placeholder="Optional description"
          className="w-full px-3 py-1.5 text-sm border border-gray-300 rounded-lg focus:outline-none focus:border-blue-500"
        />
      </div>

      <div className="flex gap-2 pt-1">
        <button
          onClick={() => createMut.mutate()}
          disabled={!name.trim() || !xml || createMut.isPending}
          className="px-4 py-1.5 text-sm bg-blue-600 text-white rounded-lg font-medium hover:bg-blue-700 disabled:opacity-50"
        >
          {createMut.isPending ? 'Uploading…' : 'Upload Profile'}
        </button>
        <button
          onClick={onDone}
          className="px-4 py-1.5 text-sm border border-gray-300 text-gray-700 rounded-lg hover:bg-gray-50"
        >
          Cancel
        </button>
      </div>
    </div>
  )
}

// ─── Compliance panel ─────────────────────────────────────────────────────────

function CompliancePanel({
  profile,
  onClose,
}: {
  profile: MobileconfigProfile
  onClose: () => void
}) {
  const toast = useToastStore(s => s.add)
  const qc = useQueryClient()

  const { data: nodes } = useQuery({
    queryKey: ['nodes-brief'],
    queryFn: () => fleetApi.nodes({ per_page: 200 }),
    staleTime: 60_000,
  })

  const { data: compliance, isLoading, isError } = useQuery<ProfileComplianceEntry[]>({
    queryKey: ['mobileconfig-compliance', profile.id],
    queryFn: () => mobileconfigApi.compliance(profile.id),
    staleTime: 30_000,
  })

  const [selectedNodes, setSelectedNodes] = useState<Set<string>>(new Set())

  const deployMut = useMutation({
    mutationFn: (action: 'install' | 'remove') =>
      mobileconfigApi.deploy(profile.id, Array.from(selectedNodes), action),
    onSuccess: (_, action) => {
      qc.invalidateQueries({ queryKey: ['mobileconfig-compliance', profile.id] })
      toast(`Deploy (${action}) queued for ${selectedNodes.size} node(s)`, 'success')
      setSelectedNodes(new Set())
    },
    onError: (e: Error) => toast(e.message, 'error'),
  })

  const allNodeIds = (nodes?.items ?? []).map(n => n.id)

  function toggleNode(id: string) {
    setSelectedNodes(prev => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  function toggleAll() {
    if (selectedNodes.size === allNodeIds.length) setSelectedNodes(new Set())
    else setSelectedNodes(new Set(allNodeIds))
  }

  return (
    <div className="bg-white border border-gray-200 rounded-xl p-5 shadow-sm">
      {/* Header */}
      <div className="flex items-start justify-between mb-4">
        <div>
          <h3 className="text-sm font-semibold text-gray-900">{profile.name}</h3>
          <div className="mt-1 space-y-0.5">
            {profile.profile_uuid && (
              <p className="text-xs text-gray-500 font-mono">{profile.profile_uuid}</p>
            )}
            <p className="text-xs text-gray-500">Version {profile.version}</p>
            {profile.description && (
              <p className="text-xs text-gray-500">{profile.description}</p>
            )}
          </div>
        </div>
        <button
          onClick={onClose}
          className="text-gray-400 hover:text-gray-600 text-lg leading-none"
          aria-label="Close compliance panel"
        >
          ✕
        </button>
      </div>

      {/* Deploy actions */}
      {selectedNodes.size > 0 && (
        <div className="mb-4 p-3 bg-blue-50 border border-blue-200 rounded-lg flex items-center gap-3">
          <span className="text-xs text-blue-700 font-medium flex-1">
            {selectedNodes.size} node(s) selected
          </span>
          <button
            onClick={() => deployMut.mutate('install')}
            disabled={deployMut.isPending}
            className="px-3 py-1.5 text-xs bg-green-600 text-white rounded-lg font-medium hover:bg-green-700 disabled:opacity-50"
          >
            Install
          </button>
          <button
            onClick={() => deployMut.mutate('remove')}
            disabled={deployMut.isPending}
            className="px-3 py-1.5 text-xs bg-red-600 text-white rounded-lg font-medium hover:bg-red-700 disabled:opacity-50"
          >
            Remove
          </button>
        </div>
      )}

      {/* Compliance table */}
      {isLoading && <Skeleton rows={3} />}
      {isError && <ErrorState message="Failed to load compliance data" />}

      {!isLoading && !isError && (
        <div className="border border-gray-200 rounded-lg overflow-hidden">
          {/* Column headers */}
          <div className="grid grid-cols-[auto_1fr_140px_160px] bg-gray-50 border-b border-gray-200 px-3 py-2 text-xs font-semibold text-gray-600">
            <div className="w-6 mr-3">
              <input
                type="checkbox"
                checked={allNodeIds.length > 0 && selectedNodes.size === allNodeIds.length}
                onChange={toggleAll}
                className="rounded border-gray-300"
              />
            </div>
            <div>Node</div>
            <div>Status</div>
            <div>Last Deployed</div>
          </div>

          {/* Node rows from fleet */}
          {allNodeIds.length === 0 ? (
            <div className="px-3 py-8 text-sm text-gray-500 text-center">
              No nodes found in the fleet.
            </div>
          ) : (
            (nodes?.items ?? []).map((node, i) => {
              const entry = compliance?.find(c => c.node_id === node.id)
              const status = entry?.status ?? 'unknown'
              const lastAt = entry?.last_deployed_at

              return (
                <div
                  key={node.id}
                  className={`grid grid-cols-[auto_1fr_140px_160px] items-center px-3 py-2.5 text-sm border-b border-gray-100 last:border-0 ${
                    i % 2 === 1 ? 'bg-gray-50/50' : 'bg-white'
                  }`}
                >
                  <div className="w-6 mr-3">
                    <input
                      type="checkbox"
                      checked={selectedNodes.has(node.id)}
                      onChange={() => toggleNode(node.id)}
                      className="rounded border-gray-300"
                    />
                  </div>
                  <div className="text-gray-900 truncate">
                    {node.hostname ?? node.minion_id ?? node.id}
                  </div>
                  <div>
                    <StatusBadge status={status} />
                  </div>
                  <div className="text-xs text-gray-500">
                    {lastAt
                      ? formatDistanceToNow(new Date(lastAt), { addSuffix: true })
                      : '—'}
                  </div>
                </div>
              )
            })
          )}
        </div>
      )}
    </div>
  )
}

// ─── Main component ───────────────────────────────────────────────────────────

export function MobileconfigManager() {
  const toast = useToastStore(s => s.add)
  const qc = useQueryClient()
  const user = useAuthStore(s => s.user)
  const isAdmin = user?.role === 'admin'

  const [showUpload, setShowUpload] = useState(false)
  const [selectedProfile, setSelectedProfile] = useState<MobileconfigProfile | null>(null)

  const {
    data: profiles,
    isLoading,
    isError,
  } = useQuery<MobileconfigProfile[]>({
    queryKey: ['mobileconfig-profiles'],
    queryFn: () => mobileconfigApi.listProfiles(),
    staleTime: 30_000,
  })

  const deleteMut = useMutation({
    mutationFn: (id: string) => mobileconfigApi.deleteProfile(id),
    onSuccess: (_, id) => {
      qc.invalidateQueries({ queryKey: ['mobileconfig-profiles'] })
      if (selectedProfile?.id === id) setSelectedProfile(null)
      toast('Profile deleted', 'success')
    },
    onError: (e: Error) => toast(e.message, 'error'),
  })

  if (isLoading) return <Skeleton rows={4} />
  if (isError) return <ErrorState message="Failed to load configuration profiles" />

  return (
    <div className="space-y-5">
      {/* Page header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-base font-semibold text-gray-900">Config Profiles</h2>
          <p className="text-xs text-gray-500 mt-0.5">
            Manage macOS configuration profiles (.mobileconfig) deployed to fleet nodes.
          </p>
        </div>
        {isAdmin && (
          <button
            onClick={() => { setShowUpload(v => !v); setSelectedProfile(null) }}
            className="px-4 py-2 text-sm bg-blue-600 text-white rounded-lg font-medium hover:bg-blue-700"
          >
            {showUpload ? 'Cancel' : '+ Upload Profile'}
          </button>
        )}
      </div>

      {/* Upload form */}
      {showUpload && (
        <div className="bg-white border border-gray-200 rounded-xl p-5 shadow-sm">
          <h3 className="text-sm font-semibold text-gray-900 mb-4">Upload Configuration Profile</h3>
          <UploadForm onDone={() => setShowUpload(false)} />
        </div>
      )}

      {/* Profile list */}
      {(profiles ?? []).length === 0 ? (
        <div className="bg-white border border-gray-200 rounded-xl p-10 text-center">
          <p className="text-sm text-gray-500">No configuration profiles yet.</p>
          {isAdmin && (
            <p className="text-xs text-gray-400 mt-1">
              Upload a .mobileconfig file to get started.
            </p>
          )}
        </div>
      ) : (
        <div className="bg-white border border-gray-200 rounded-xl overflow-hidden shadow-sm">
          {/* Table header */}
          <div className="grid grid-cols-[1fr_180px_80px_100px_80px] bg-gray-50 border-b border-gray-200 px-4 py-2.5 text-xs font-semibold text-gray-600 uppercase tracking-wide">
            <div>Name</div>
            <div>Profile UUID</div>
            <div>Version</div>
            <div>Uploaded</div>
            <div />
          </div>

          {/* Rows */}
          {(profiles ?? []).map((profile, i) => (
            <div key={profile.id}>
              <div
                className={`grid grid-cols-[1fr_180px_80px_100px_80px] items-center px-4 py-3 border-b border-gray-100 last:border-0 cursor-pointer hover:bg-blue-50/30 transition-colors ${
                  i % 2 === 1 ? 'bg-gray-50/40' : 'bg-white'
                } ${selectedProfile?.id === profile.id ? 'bg-blue-50 border-l-2 border-l-blue-500' : ''}`}
                onClick={() =>
                  setSelectedProfile(prev => (prev?.id === profile.id ? null : profile))
                }
              >
                <div>
                  <p className="text-sm font-medium text-gray-900">{profile.name}</p>
                  {profile.description && (
                    <p className="text-xs text-gray-500 truncate">{profile.description}</p>
                  )}
                </div>
                <div className="text-xs font-mono text-gray-500 truncate">
                  {profile.profile_uuid ?? <span className="text-gray-400 italic">none</span>}
                </div>
                <div className="text-xs text-gray-600 font-medium">v{profile.version}</div>
                <div className="text-xs text-gray-500">
                  {formatDistanceToNow(new Date(profile.created_at), { addSuffix: true })}
                </div>
                <div
                  className="flex justify-end"
                  onClick={e => e.stopPropagation()}
                >
                  {isAdmin && (
                    <button
                      onClick={() => {
                        if (confirm(`Delete profile "${profile.name}"?`)) {
                          deleteMut.mutate(profile.id)
                        }
                      }}
                      disabled={deleteMut.isPending}
                      className="text-xs text-red-500 hover:text-red-700 disabled:opacity-40 px-2 py-1"
                      title="Delete profile"
                    >
                      Delete
                    </button>
                  )}
                </div>
              </div>

              {/* Inline compliance panel */}
              {selectedProfile?.id === profile.id && (
                <div className="px-4 pb-4 pt-2 bg-blue-50/20 border-b border-gray-100">
                  <CompliancePanel
                    profile={profile}
                    onClose={() => setSelectedProfile(null)}
                  />
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
