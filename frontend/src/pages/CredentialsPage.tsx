import { useState, type FormEvent } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { credentialsApi, type Credential, type CredentialCreate } from '../api/credentials'
import { groupsApi } from '../api/groups'
import { ApiError } from '../api/client'
import { Skeleton } from '../components/Skeleton'
import { ErrorState } from '../components/ErrorState'
import { ConfirmDialog } from '../components/ConfirmDialog'
import { SecretInput } from '../components/SecretInput'
import { useToastStore } from '../stores/toastStore'
import { useFocusTrap } from '../hooks/useFocusTrap'
import { formatLocalDateTime } from '../utils/time'

type CredentialKind = 'username_password' | 'ssh_key'

const inputClass =
  'w-full px-3 py-2 border border-gray-300 rounded-lg text-sm text-gray-900 focus:outline-hidden focus:border-brand-600'
const btnPrimary =
  'px-4 py-2 bg-brand-600 text-white text-sm rounded-lg font-medium hover:bg-brand-700 disabled:opacity-50'
const btnSecondary =
  'px-4 py-2 bg-white border border-gray-300 text-gray-700 text-sm rounded-lg font-medium hover:bg-gray-50 disabled:opacity-50'

const KIND_STYLES: Record<string, string> = {
  token: 'bg-blue-100 text-blue-700',
  ssh_key: 'bg-purple-100 text-purple-700',
  username_password: 'bg-emerald-100 text-emerald-700',
}

const KIND_LABELS: Record<string, string> = {
  token: 'Token',
  ssh_key: 'SSH Key',
  username_password: 'Username + Password',
}

function KindBadge({ kind }: { kind: string }) {
  return (
    <span
      className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${
        KIND_STYLES[kind] ?? 'bg-gray-100 text-gray-600'
      }`}
    >
      {KIND_LABELS[kind] ?? kind}
    </span>
  )
}

interface CredentialFormModalProps {
  mode: 'create' | 'edit'
  credential?: Credential
  onClose: () => void
}

function CredentialFormModal({ mode, credential, onClose }: CredentialFormModalProps) {
  const qc = useQueryClient()
  const toast = useToastStore((s) => s.add)
  const containerRef = useFocusTrap<HTMLDivElement>(true, onClose)

  const [name, setName] = useState(credential?.name ?? '')
  const [kind, setKind] = useState<CredentialKind>(
    (credential?.kind as CredentialKind | undefined) ?? 'username_password',
  )
  const [username, setUsername] = useState(credential?.username ?? '')
  const [secret, setSecret] = useState('')

  const createMutation = useMutation({
    mutationFn: (body: CredentialCreate) => credentialsApi.create(body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['credentials'] })
      toast('Credential created')
      onClose()
    },
    onError: (e: Error) => toast(e.message, 'error'),
  })

  const updateMutation = useMutation({
    mutationFn: (body: Partial<CredentialCreate>) => credentialsApi.update(credential!.id, body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['credentials'] })
      toast('Credential updated')
      onClose()
    },
    onError: (e: Error) => toast(e.message, 'error'),
  })

  const isPending = createMutation.isPending || updateMutation.isPending

  function submit(e: FormEvent) {
    e.preventDefault()
    if (mode === 'create') {
      createMutation.mutate({
        name: name.trim(),
        kind,
        username: username.trim() || undefined,
        secret,
      })
    } else {
      const body: Partial<CredentialCreate> = {
        name: name.trim(),
        username: username.trim() || undefined,
      }
      if (secret) body.secret = secret
      updateMutation.mutate(body)
    }
  }

  const canSubmit = name.trim().length > 0 && (mode === 'edit' || secret.length > 0)

  return (
    <div
      ref={containerRef}
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40"
      role="dialog"
      aria-modal="true"
      aria-labelledby="credential-form-title"
    >
      <form
        onSubmit={submit}
        className="bg-white rounded-xl shadow-2xl p-6 w-full max-w-md mx-4 border border-gray-200 space-y-4"
      >
        <h2 id="credential-form-title" className="text-base font-semibold text-gray-900">
          {mode === 'create' ? 'New Credential' : `Edit "${credential?.name}"`}
        </h2>

        <div>
          <label className="block text-xs font-medium text-gray-600 mb-1">Name</label>
          <input
            autoFocus
            required
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="e.g. Prod SSH"
            className={inputClass}
          />
        </div>

        {mode === 'create' && (
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">Type</label>
            <div className="flex gap-2">
              <button
                type="button"
                onClick={() => setKind('username_password')}
                className={`px-3 py-1.5 rounded-lg text-sm font-medium border transition-colors ${
                  kind === 'username_password'
                    ? 'bg-brand-600 text-white border-brand-600'
                    : 'bg-white text-gray-700 border-gray-300 hover:bg-gray-50'
                }`}
              >
                Username + Password
              </button>
              <button
                type="button"
                onClick={() => setKind('ssh_key')}
                className={`px-3 py-1.5 rounded-lg text-sm font-medium border transition-colors ${
                  kind === 'ssh_key'
                    ? 'bg-brand-600 text-white border-brand-600'
                    : 'bg-white text-gray-700 border-gray-300 hover:bg-gray-50'
                }`}
              >
                SSH Key
              </button>
            </div>
          </div>
        )}

        <div>
          <label className="block text-xs font-medium text-gray-600 mb-1">Username</label>
          <input
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            placeholder="admin"
            className={inputClass}
          />
        </div>

        <div>
          <label className="block text-xs font-medium text-gray-600 mb-1">
            {kind === 'ssh_key' ? 'Private Key' : 'Password'}
            {mode === 'edit' && (
              <span className="text-gray-400 font-normal"> (saved — leave blank to keep)</span>
            )}
          </label>
          {kind === 'ssh_key' ? (
            <textarea
              value={secret}
              onChange={(e) => setSecret(e.target.value)}
              rows={6}
              placeholder={
                mode === 'edit'
                  ? '•••••••• (saved — paste to replace)'
                  : 'Paste an OpenSSH private key (BEGIN…KEY block)'
              }
              className={`${inputClass} font-mono resize-none`}
            />
          ) : (
            <SecretInput
              value={secret}
              onChange={setSecret}
              placeholder={mode === 'edit' ? '•••••••• (saved — leave blank to keep)' : 'Enter password'}
              className={inputClass}
            />
          )}
        </div>

        <div className="flex justify-end gap-3 pt-2">
          <button type="button" onClick={onClose} className={btnSecondary}>
            Cancel
          </button>
          <button type="submit" disabled={!canSubmit || isPending} className={btnPrimary}>
            {isPending ? 'Saving…' : mode === 'create' ? 'Create' : 'Save'}
          </button>
        </div>
      </form>
    </div>
  )
}

interface AssociatedGroupsModalProps {
  credential: Credential
  onClose: () => void
}

function AssociatedGroupsModal({ credential, onClose }: AssociatedGroupsModalProps) {
  const qc = useQueryClient()
  const toast = useToastStore((s) => s.add)
  const containerRef = useFocusTrap<HTMLDivElement>(true, onClose)
  const [selected, setSelected] = useState<Set<string> | null>(null)

  const { data: groupsPage, isLoading: groupsLoading } = useQuery({
    queryKey: ['groups-all-for-credential-picker'],
    queryFn: () => groupsApi.list({ page: 1, per_page: 200 }),
    staleTime: 30_000,
  })
  const groups = groupsPage?.items ?? []

  // One request per group to read its current credential — matches the
  // per-row query pattern already used by CredentialUsage in SettingsPage.
  // There is no bulk "groups for credential" endpoint yet.
  const { data: assocMap, isLoading: assocLoading } = useQuery({
    queryKey: ['credential-group-membership', credential.id, groups.map((g) => g.id).join(',')],
    queryFn: async () => {
      const entries = await Promise.all(
        groups.map(async (g) => {
          const gc = await groupsApi.getCredentials(g.id)
          return [g.id, gc.credential_id === credential.id] as const
        }),
      )
      return new Map(entries)
    },
    enabled: groups.length > 0,
  })

  // Initialise local selection once membership data arrives (established
  // pattern in this codebase — see GroupDetail's credFormInit).
  if (assocMap && selected === null) {
    setSelected(new Set([...assocMap.entries()].filter(([, checked]) => checked).map(([id]) => id)))
  }

  const loading = groupsLoading || assocLoading || selected === null

  function toggle(id: string) {
    if (!selected) return
    const next = new Set(selected)
    if (next.has(id)) next.delete(id)
    else next.add(id)
    setSelected(next)
  }

  const saveMutation = useMutation({
    mutationFn: async () => {
      if (!selected || !assocMap) return
      const toAdd = [...selected].filter((id) => !assocMap.get(id))
      const toRemove = [...assocMap.keys()].filter((id) => assocMap.get(id) && !selected.has(id))
      await Promise.all([
        ...toAdd.map((id) => groupsApi.associateCredential(id, credential.id)),
        ...toRemove.map((id) => groupsApi.associateCredential(id, null)),
      ])
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['credentials'] })
      qc.invalidateQueries({ queryKey: ['credential-group-membership'] })
      qc.invalidateQueries({ queryKey: ['group-credentials'] })
      toast('Associated groups updated')
      onClose()
    },
    onError: (e: Error) => toast(e.message, 'error'),
  })

  return (
    <div
      ref={containerRef}
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40"
      role="dialog"
      aria-modal="true"
      aria-labelledby="assoc-groups-title"
    >
      <div className="bg-white rounded-xl shadow-2xl p-6 w-full max-w-md mx-4 border border-gray-200 max-h-[80vh] flex flex-col">
        <h2 id="assoc-groups-title" className="text-base font-semibold text-gray-900 mb-1">
          Associated Groups
        </h2>
        <p className="text-xs text-gray-500 mb-4">
          Groups whose nodes will use &quot;{credential.name}&quot; for SSH access.
        </p>

        <div className="flex-1 overflow-y-auto border border-gray-200 rounded-lg divide-y divide-gray-100">
          {loading ? (
            <Skeleton rows={4} />
          ) : groups.length === 0 ? (
            <div className="px-4 py-8 text-center text-gray-400 text-sm">No groups exist yet.</div>
          ) : (
            groups.map((g) => (
              <label
                key={g.id}
                className="flex items-center gap-3 px-3 py-2.5 text-sm cursor-pointer hover:bg-gray-50"
              >
                <input
                  type="checkbox"
                  checked={selected?.has(g.id) ?? false}
                  onChange={() => toggle(g.id)}
                  className="accent-brand-600 cursor-pointer"
                />
                <span className="text-gray-900 font-medium">{g.name}</span>
                <span className="text-xs text-gray-400 ml-auto">{g.type}</span>
              </label>
            ))
          )}
        </div>

        <div className="flex justify-end gap-3 pt-4">
          <button onClick={onClose} className={btnSecondary}>
            Cancel
          </button>
          <button
            onClick={() => saveMutation.mutate()}
            disabled={loading || saveMutation.isPending}
            className={btnPrimary}
          >
            {saveMutation.isPending ? 'Saving…' : 'Save'}
          </button>
        </div>
      </div>
    </div>
  )
}

export function CredentialsPage() {
  const qc = useQueryClient()
  const toast = useToastStore((s) => s.add)

  const [formTarget, setFormTarget] = useState<'create' | Credential | null>(null)
  const [deleteTarget, setDeleteTarget] = useState<Credential | null>(null)
  const [forceDeleteTarget, setForceDeleteTarget] = useState<Credential | null>(null)
  const [groupsTarget, setGroupsTarget] = useState<Credential | null>(null)

  const {
    data: credentials,
    isLoading,
    isError,
    refetch,
  } = useQuery({
    queryKey: ['credentials'],
    queryFn: credentialsApi.list,
  })

  const deleteMutation = useMutation({
    mutationFn: (id: string) => credentialsApi.remove(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['credentials'] })
      toast('Credential deleted')
    },
    onError: (e: Error, id: string) => {
      const cred = credentials?.find((c) => c.id === id)
      if (e instanceof ApiError && e.status === 409 && cred) {
        setForceDeleteTarget(cred)
      } else {
        toast(e.message, 'error')
      }
    },
  })

  const forceDeleteMutation = useMutation({
    mutationFn: (id: string) => credentialsApi.remove(id, true),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['credentials'] })
      toast('Credential force-deleted — references detached')
    },
    onError: (e: Error) => toast(e.message, 'error'),
  })

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Credentials</h1>
          <p className="text-sm text-gray-500 mt-0.5">
            Shared credentials for node and group SSH access.
          </p>
        </div>
        <button onClick={() => setFormTarget('create')} className={btnPrimary}>
          + New credential
        </button>
      </div>

      <div className="bg-white rounded-xl border border-gray-200 shadow-xs overflow-hidden">
        {isLoading ? (
          <Skeleton rows={6} />
        ) : isError ? (
          <ErrorState message="Failed to load credentials" retry={refetch} />
        ) : !credentials || credentials.length === 0 ? (
          <div className="px-4 py-12 text-center text-gray-400 text-sm">
            No credentials yet. Click &quot;+ New credential&quot; to add one.
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-gray-50 border-b border-gray-200 text-left text-xs font-semibold text-gray-500 uppercase tracking-wide">
                <th scope="col" className="px-4 py-3">Name</th>
                <th scope="col" className="px-4 py-3">Type</th>
                <th scope="col" className="px-4 py-3">Username</th>
                <th scope="col" className="px-4 py-3">Groups</th>
                <th scope="col" className="px-4 py-3">Nodes</th>
                <th scope="col" className="px-4 py-3">Last Used</th>
                <th scope="col" className="px-4 py-3 w-40"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {credentials.map((cred) => (
                <tr key={cred.id} className="hover:bg-gray-50 transition-colors">
                  <td className="px-4 py-3 font-medium text-gray-900">{cred.name}</td>
                  <td className="px-4 py-3"><KindBadge kind={cred.kind} /></td>
                  <td className="px-4 py-3 text-gray-600 font-mono text-xs">{cred.username ?? '—'}</td>
                  <td className="px-4 py-3">
                    <button
                      onClick={() => setGroupsTarget(cred)}
                      className="text-xs text-brand-600 hover:text-brand-700 font-medium"
                    >
                      {cred.group_count ?? '—'} {cred.group_count === 1 ? 'group' : 'groups'}
                    </button>
                  </td>
                  <td className="px-4 py-3 text-gray-600 text-xs">{cred.node_count ?? '—'}</td>
                  <td className="px-4 py-3 text-gray-400 text-xs">
                    {cred.last_used_at ? formatLocalDateTime(cred.last_used_at) : 'Never'}
                  </td>
                  <td className="px-4 py-3 text-right whitespace-nowrap space-x-3">
                    <button
                      onClick={() => setFormTarget(cred)}
                      className="text-xs text-brand-600 hover:text-brand-700 font-medium"
                    >
                      Edit
                    </button>
                    <button
                      onClick={() => setDeleteTarget(cred)}
                      disabled={deleteMutation.isPending}
                      className="text-xs text-red-500 hover:text-red-700 font-medium disabled:opacity-50"
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

      {formTarget && (
        <CredentialFormModal
          mode={formTarget === 'create' ? 'create' : 'edit'}
          credential={formTarget === 'create' ? undefined : formTarget}
          onClose={() => setFormTarget(null)}
        />
      )}

      {groupsTarget && (
        <AssociatedGroupsModal credential={groupsTarget} onClose={() => setGroupsTarget(null)} />
      )}

      {deleteTarget && (
        <ConfirmDialog
          title={`Delete credential "${deleteTarget.name}"?`}
          message="This cannot be undone."
          confirmLabel="Delete"
          destructive
          onConfirm={() => {
            deleteMutation.mutate(deleteTarget.id)
            setDeleteTarget(null)
          }}
          onCancel={() => setDeleteTarget(null)}
        />
      )}

      {forceDeleteTarget && (
        <ConfirmDialog
          title={`"${forceDeleteTarget.name}" is still in use`}
          message="This credential is referenced by nodes or groups. Force delete will detach all references. This cannot be undone."
          confirmLabel="Force delete"
          destructive
          onConfirm={() => {
            forceDeleteMutation.mutate(forceDeleteTarget.id)
            setForceDeleteTarget(null)
          }}
          onCancel={() => setForceDeleteTarget(null)}
        />
      )}
    </div>
  )
}
