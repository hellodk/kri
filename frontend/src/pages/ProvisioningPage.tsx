import { useCallback, useRef, useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { formatDistanceToNow, differenceInDays } from 'date-fns'
import { provisioningApi, type ProvisioningProfile } from '../api/provisioning'
import { useToastStore } from '../stores/toastStore'
import { Skeleton } from '../components/Skeleton'
import { ErrorState } from '../components/ErrorState'

// ─── Type badge ────────────────────────────────────────────────────────────────

const TYPE_STYLES: Record<string, string> = {
  development: 'bg-blue-50 text-blue-700 border-blue-200',
  adhoc: 'bg-amber-50 text-amber-700 border-amber-200',
  distribution: 'bg-emerald-50 text-emerald-700 border-emerald-200',
}

const TYPE_LABELS: Record<string, string> = {
  development: 'Development',
  adhoc: 'Ad Hoc',
  distribution: 'Distribution',
}

function TypeBadge({ type }: { type: string }) {
  return (
    <span
      className={`text-xs px-2 py-0.5 rounded font-medium border ${
        TYPE_STYLES[type] ?? 'bg-gray-50 text-gray-700 border-gray-200'
      }`}
    >
      {TYPE_LABELS[type] ?? type}
    </span>
  )
}

// ─── Expiry display ────────────────────────────────────────────────────────────

function ExpiryCell({ expiryDate }: { expiryDate: string | null }) {
  if (!expiryDate) return <span className="text-gray-400 text-xs">—</span>

  const date = new Date(expiryDate)
  const daysLeft = differenceInDays(date, new Date())

  const colorClass =
    daysLeft < 0
      ? 'text-red-600 font-semibold'
      : daysLeft < 30
      ? 'text-red-500'
      : daysLeft < 90
      ? 'text-amber-600'
      : 'text-gray-500'

  const label =
    daysLeft < 0
      ? 'Expired'
      : daysLeft === 0
      ? 'Expires today'
      : `${daysLeft}d left`

  return (
    <div className="text-xs">
      <span className={colorClass}>{label}</span>
      <span className="text-gray-400 ml-1">
        ({date.toLocaleDateString()})
      </span>
    </div>
  )
}

// ─── Upload modal ──────────────────────────────────────────────────────────────

function UploadModal({ onClose }: { onClose: () => void }) {
  const qc = useQueryClient()
  const toast = useToastStore((s) => s.add)
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [file, setFile] = useState<File | null>(null)
  const [dragging, setDragging] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

  const uploadMutation = useMutation({
    mutationFn: () => {
      if (!file) throw new Error('No file selected')
      return provisioningApi.upload(name, file, description || undefined)
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['provisioning-profiles'] })
      toast('Profile uploaded successfully')
      onClose()
    },
    onError: (e: Error) => toast(e.message, 'error'),
  })

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    setDragging(false)
    const dropped = e.dataTransfer.files[0]
    if (dropped?.name.endsWith('.mobileprovision')) {
      setFile(dropped)
      if (!name) setName(dropped.name.replace('.mobileprovision', ''))
    } else {
      toast('Please drop a .mobileprovision file', 'error')
    }
  }, [name, toast])

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0]
    if (f) {
      setFile(f)
      if (!name) setName(f.name.replace('.mobileprovision', ''))
    }
  }

  const canSubmit = !!name && !!file && !uploadMutation.isPending

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-lg flex flex-col max-h-[92vh]">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200">
          <h2 className="text-lg font-bold text-gray-900">Upload Provisioning Profile</h2>
          <button
            onClick={onClose}
            className="flex items-center justify-center w-8 h-8 rounded-lg text-gray-400 hover:text-gray-600 hover:bg-gray-100 transition-colors text-lg"
          >
            ×
          </button>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto px-6 py-5 space-y-5">
          {/* Name */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Profile name
            </label>
            <input
              required
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="MyApp Distribution"
              className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm text-gray-900 focus:outline-none focus:border-brand-600"
            />
          </div>

          {/* Description */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Description <span className="text-gray-400 font-normal">(optional)</span>
            </label>
            <input
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="Production distribution profile for MyApp"
              className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm text-gray-900 focus:outline-none focus:border-brand-600"
            />
          </div>

          {/* File drop zone */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Profile file
            </label>
            <div
              onDragOver={(e) => { e.preventDefault(); setDragging(true) }}
              onDragLeave={() => setDragging(false)}
              onDrop={handleDrop}
              onClick={() => inputRef.current?.click()}
              className={`relative cursor-pointer border-2 border-dashed rounded-xl p-8 text-center transition-colors ${
                dragging
                  ? 'border-brand-500 bg-brand-50'
                  : file
                  ? 'border-emerald-400 bg-emerald-50'
                  : 'border-gray-300 hover:border-brand-400 hover:bg-gray-50'
              }`}
            >
              <input
                ref={inputRef}
                type="file"
                accept=".mobileprovision"
                className="hidden"
                onChange={handleFileChange}
              />
              {file ? (
                <div className="space-y-1">
                  <p className="text-sm font-medium text-emerald-700">{file.name}</p>
                  <p className="text-xs text-emerald-600">
                    {(file.size / 1024).toFixed(1)} KB — click to change
                  </p>
                </div>
              ) : (
                <div className="space-y-2">
                  <p className="text-sm text-gray-500">
                    Drag and drop your <code className="text-xs bg-gray-100 px-1 py-0.5 rounded">.mobileprovision</code> file here
                  </p>
                  <p className="text-xs text-gray-400">or click to browse</p>
                </div>
              )}
            </div>
          </div>
        </div>

        {/* Footer */}
        <div className="px-6 py-4 border-t border-gray-200">
          <div className="flex gap-3">
            <button
              onClick={onClose}
              className="flex-1 py-2.5 border border-gray-300 text-gray-700 rounded-lg text-sm font-medium hover:bg-gray-50"
            >
              Cancel
            </button>
            <button
              disabled={!canSubmit}
              onClick={() => uploadMutation.mutate()}
              className="flex-1 py-2.5 bg-brand-600 text-white rounded-lg text-sm font-medium hover:bg-brand-700 disabled:opacity-50"
            >
              {uploadMutation.isPending ? 'Uploading…' : 'Upload Profile'}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

// ─── Delete confirmation ───────────────────────────────────────────────────────

function DeleteConfirmModal({
  profile,
  onClose,
}: {
  profile: ProvisioningProfile
  onClose: () => void
}) {
  const qc = useQueryClient()
  const toast = useToastStore((s) => s.add)

  const deleteMutation = useMutation({
    mutationFn: () => provisioningApi.delete(profile.id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['provisioning-profiles'] })
      toast('Profile deleted')
      onClose()
    },
    onError: (e: Error) => toast(e.message, 'error'),
  })

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-sm p-6 space-y-4">
        <h2 className="text-lg font-bold text-gray-900">Delete profile?</h2>
        <p className="text-sm text-gray-600">
          <strong>{profile.name}</strong> will be permanently removed. This cannot be undone.
        </p>
        <div className="flex gap-3 pt-2">
          <button
            onClick={onClose}
            className="flex-1 py-2.5 border border-gray-300 text-gray-700 rounded-lg text-sm font-medium hover:bg-gray-50"
          >
            Cancel
          </button>
          <button
            disabled={deleteMutation.isPending}
            onClick={() => deleteMutation.mutate()}
            className="flex-1 py-2.5 bg-red-600 text-white rounded-lg text-sm font-medium hover:bg-red-700 disabled:opacity-50"
          >
            {deleteMutation.isPending ? 'Deleting…' : 'Delete'}
          </button>
        </div>
      </div>
    </div>
  )
}

// ─── Main page ─────────────────────────────────────────────────────────────────

export function ProvisioningPage() {
  const [showUpload, setShowUpload] = useState(false)
  const [toDelete, setToDelete] = useState<ProvisioningProfile | null>(null)

  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ['provisioning-profiles'],
    queryFn: () => provisioningApi.list(),
    staleTime: 30_000,
  })

  return (
    <div className="space-y-6">
      {/* Page header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Provisioning Profiles</h1>
          <p className="text-gray-500 mt-1 text-sm">
            Upload and manage Apple provisioning profiles for distribution to managed Mac Minis.
          </p>
        </div>
        <button
          onClick={() => setShowUpload(true)}
          className="px-4 py-2 bg-brand-600 text-white text-sm font-medium rounded-lg hover:bg-brand-700 shadow-sm"
        >
          + Upload Profile
        </button>
      </div>

      {/* Info banner */}
      <div className="bg-brand-50 border border-brand-200 rounded-xl p-4 text-sm text-brand-800 space-y-1">
        <p className="font-semibold">About provisioning profiles</p>
        <p>
          Apple provisioning profiles (<code className="text-xs bg-brand-100 px-1 py-0.5 rounded">.mobileprovision</code>)
          authorize apps to run on specific devices or be distributed via the App Store.
          Upload profiles here to store them centrally — kri will distribute and install them
          on managed devices via SaltStack.
        </p>
        <p className="text-xs text-brand-600 mt-1">
          Supported types: <strong>Development</strong> (debug builds), <strong>Ad Hoc</strong> (specific device lists),
          and <strong>Distribution</strong> (App Store / enterprise).
        </p>
      </div>

      {/* Content */}
      {isLoading ? (
        <Skeleton rows={4} />
      ) : isError ? (
        <ErrorState message="Failed to load provisioning profiles" retry={refetch} />
      ) : data?.items.length === 0 ? (
        <div className="bg-white rounded-xl border border-gray-200 p-12 text-center space-y-3">
          <div className="text-4xl text-gray-300 mx-auto">shield</div>
          <p className="text-gray-400 text-sm">No provisioning profiles uploaded yet.</p>
          <button
            onClick={() => setShowUpload(true)}
            className="px-4 py-2 bg-brand-600 text-white text-sm font-medium rounded-lg hover:bg-brand-700"
          >
            Upload your first profile
          </button>
        </div>
      ) : (
        <div className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-gray-50 border-b border-gray-200 text-left text-xs font-semibold text-gray-500 uppercase tracking-wide">
                <th className="px-4 py-3">Name</th>
                <th className="px-4 py-3">Bundle ID</th>
                <th className="px-4 py-3">Team</th>
                <th className="px-4 py-3">Type</th>
                <th className="px-4 py-3">Expiry</th>
                <th className="px-4 py-3">Uploaded by</th>
                <th className="px-4 py-3">Uploaded</th>
                <th className="px-4 py-3 w-28"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {data?.items.map((p) => (
                <tr key={p.id} className="hover:bg-gray-50 transition-colors">
                  <td className="px-4 py-3">
                    <p className="font-medium text-gray-900">{p.name}</p>
                    {p.description && (
                      <p className="text-xs text-gray-400 mt-0.5">{p.description}</p>
                    )}
                    <p className="text-xs text-gray-400 font-mono mt-0.5">{p.filename}</p>
                  </td>
                  <td className="px-4 py-3 text-xs text-gray-500 font-mono">
                    {p.bundle_id ?? <span className="text-gray-300">—</span>}
                  </td>
                  <td className="px-4 py-3 text-xs text-gray-500">
                    {p.team_name ?? <span className="text-gray-300">—</span>}
                  </td>
                  <td className="px-4 py-3">
                    <TypeBadge type={p.profile_type} />
                  </td>
                  <td className="px-4 py-3">
                    <ExpiryCell expiryDate={p.expiry_date} />
                  </td>
                  <td className="px-4 py-3 text-xs text-gray-500">{p.uploaded_by}</td>
                  <td className="px-4 py-3 text-xs text-gray-400">
                    {formatDistanceToNow(new Date(p.created_at), { addSuffix: true })}
                  </td>
                  <td className="px-4 py-3 text-right">
                    <div className="flex items-center justify-end gap-2">
                      <button
                        onClick={() => provisioningApi.download(p.id, p.filename)}
                        className="text-xs text-brand-600 hover:text-brand-700 font-medium"
                        title="Download"
                      >
                        Download
                      </button>
                      <button
                        onClick={() => setToDelete(p)}
                        className="text-xs text-red-500 hover:text-red-700 font-medium"
                        title="Delete"
                      >
                        Delete
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {showUpload && <UploadModal onClose={() => setShowUpload(false)} />}
      {toDelete && <DeleteConfirmModal profile={toDelete} onClose={() => setToDelete(null)} />}
    </div>
  )
}
