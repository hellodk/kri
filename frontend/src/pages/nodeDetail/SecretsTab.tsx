import { memo, useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { fleetApi } from '../../api/fleet'
import { nodeSecretsApi } from '../../api/nodeSecrets'
import { formatIST } from '../../utils/time'
import { ConfirmDialog } from '../../components/ConfirmDialog'
import { useToastStore } from '../../stores/toastStore'
import type { NodeDetail as NodeDetailData } from '../../types'

export const SecretsTab = memo(function SecretsTab({
  node,
  nodeId,
}: {
  node: NodeDetailData
  nodeId: string
}) {
  const qc = useQueryClient()
  const toast = useToastStore((s) => s.add)
  const [secretKey, setSecretKey] = useState('')
  const [secretValue, setSecretValue] = useState('')
  const [secretDesc, setSecretDesc] = useState('')
  const [secretShowValue, setSecretShowValue] = useState(false)
  const [deletingSecretKey, setDeletingSecretKey] = useState<string | null>(null)
  const [vncPasswordInput, setVncPasswordInput] = useState('')
  const [showVncPassword, setShowVncPassword] = useState(false)

  const { data: nodeSecrets } = useQuery({
    queryKey: ['node-secrets', nodeId],
    queryFn: () => nodeSecretsApi.list(nodeId),
    staleTime: 30_000,
    enabled: !!nodeId,
  })

  const addSecretMutation = useMutation({
    mutationFn: () =>
      nodeSecretsApi.upsert(nodeId, secretKey.trim(), secretValue, secretDesc.trim() || undefined),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['node-secrets', nodeId] })
      setSecretKey('')
      setSecretValue('')
      setSecretDesc('')
      toast('Secret saved')
    },
    onError: (e: Error) => toast(e.message, 'error'),
  })

  const deleteSecretMutation = useMutation({
    mutationFn: (key: string) => nodeSecretsApi.delete(nodeId, key),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['node-secrets', nodeId] })
      toast('Secret deleted')
    },
    onError: (e: Error) => toast(e.message, 'error'),
  })

  const saveVncPasswordMutation = useMutation({
    mutationFn: () => fleetApi.updateNode(nodeId, { vnc_password: vncPasswordInput }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['node', nodeId] })
      setVncPasswordInput('')
      toast('VNC password saved')
    },
    onError: (e: Error) => toast(e.message, 'error'),
  })

  return (
    <div role="tabpanel" id="tabpanel-secrets" aria-labelledby="tab-secrets" className="space-y-4">
      {/* Info banner */}
      <div className="bg-amber-50 border border-amber-200 rounded-xl p-4 flex items-start gap-3">
        <span className="text-amber-500 text-lg mt-0.5">ℹ</span>
        <p className="text-sm text-amber-800">
          Secrets are injected into this node's Salt pillar and available as{' '}
          <code className="font-mono bg-amber-100 px-1 rounded">{'{{ pillar[\'key\'] }}'}</code>{' '}
          in Salt states and templates.
        </p>
      </div>

      {/* Existing secrets table */}
      <div className="bg-white rounded-xl border border-gray-200 shadow-xs overflow-hidden">
        <div className="px-4 py-3 border-b border-gray-200">
          <p className="text-sm font-semibold text-gray-700">Stored Secrets</p>
          <p className="text-xs text-gray-500 mt-0.5">Values are write-only and never displayed.</p>
        </div>
        {!nodeSecrets || nodeSecrets.length === 0 ? (
          <div className="px-4 py-8 text-center text-gray-600 text-sm">No secrets stored for this node.</div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-gray-50 border-b border-gray-200 text-left text-xs font-semibold text-gray-500 uppercase tracking-wide">
                <th scope="col" className="px-4 py-3">Key</th>
                <th scope="col" className="px-4 py-3">Description</th>
                <th scope="col" className="px-4 py-3">Last Updated</th>
                <th scope="col" className="px-4 py-3 w-20"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {nodeSecrets.map((s) => (
                <tr key={s.key} className="hover:bg-gray-50">
                  <td className="px-4 py-3 font-mono font-medium text-gray-900">{s.key}</td>
                  <td className="px-4 py-3 text-gray-500 text-xs">{s.description ?? '—'}</td>
                  <td className="px-4 py-3 text-gray-500 text-xs">
                    {formatIST(s.updated_at)}
                  </td>
                  <td className="px-4 py-3 text-right">
                    <button
                      onClick={() => setDeletingSecretKey(s.key)}
                      disabled={deleteSecretMutation.isPending}
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

      {/* Add secret form */}
      <div className="bg-white rounded-xl border border-gray-200 shadow-xs p-4 space-y-3">
        <p className="text-sm font-semibold text-gray-700">Add / Update Secret</p>
        <form
          onSubmit={(e) => { e.preventDefault(); addSecretMutation.mutate() }}
          className="space-y-3"
        >
          <div className="flex gap-3 flex-wrap">
            <div className="flex-1 min-w-32">
              <label className="block text-xs text-gray-500 mb-1">Key</label>
              <input
                value={secretKey}
                onChange={(e) => setSecretKey(e.target.value)}
                placeholder="e.g. jenkins_slave_secret"
                required
                className="w-full text-sm border border-gray-300 rounded px-2 py-1.5 font-mono focus:outline-hidden focus:ring-2 focus:ring-brand-400"
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
                  className="w-full text-sm border border-gray-300 rounded px-2 py-1.5 pr-16 focus:outline-hidden focus:ring-2 focus:ring-brand-400"
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
                className="w-full text-sm border border-gray-300 rounded px-2 py-1.5 focus:outline-hidden focus:ring-2 focus:ring-brand-400"
              />
            </div>
          </div>
          <div className="flex justify-end">
            <button
              type="submit"
              disabled={addSecretMutation.isPending || !secretKey.trim() || !secretValue}
              className="px-4 py-2 bg-brand-600 text-white text-sm rounded-lg hover:bg-brand-700 disabled:opacity-50 font-medium"
            >
              {addSecretMutation.isPending ? 'Saving…' : 'Save Secret'}
            </button>
          </div>
        </form>
      </div>

      {/* VNC Password card */}
      <div className="bg-white rounded-xl border border-gray-200 shadow-xs p-4 space-y-3">
        <div className="flex items-center gap-2">
          <p className="text-sm font-semibold text-gray-700">VNC Password</p>
          {node.has_vnc_password && (
            <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-emerald-100 text-emerald-700 border border-emerald-200">
              Stored
            </span>
          )}
        </div>
        <p className="text-xs text-gray-500">
          Used by the kri VNC proxy to authenticate server-side against macOS Screen Sharing (port 5900).
          The password is encrypted at rest and never transmitted to the browser.
        </p>
        <form
          onSubmit={(e) => { e.preventDefault(); saveVncPasswordMutation.mutate() }}
          className="flex gap-3 flex-wrap items-end"
        >
          <div className="flex-1 min-w-48">
            <label className="block text-xs text-gray-500 mb-1">New VNC Password</label>
            <div className="relative">
              <input
                type={showVncPassword ? 'text' : 'password'}
                value={vncPasswordInput}
                onChange={(e) => setVncPasswordInput(e.target.value)}
                placeholder={node.has_vnc_password ? 'Leave blank to keep existing' : 'Enter VNC password'}
                className="w-full text-sm border border-gray-300 rounded px-2 py-1.5 pr-16 focus:outline-hidden focus:ring-2 focus:ring-brand-400"
              />
              <button
                type="button"
                onClick={() => setShowVncPassword((v) => !v)}
                className="absolute right-2 top-1/2 -translate-y-1/2 text-xs text-gray-400 hover:text-gray-600"
              >
                {showVncPassword ? 'Hide' : 'Show'}
              </button>
            </div>
          </div>
          <button
            type="submit"
            disabled={saveVncPasswordMutation.isPending || !vncPasswordInput}
            className="px-4 py-1.5 bg-brand-600 text-white text-sm rounded-lg hover:bg-brand-700 disabled:opacity-50 font-medium"
          >
            {saveVncPasswordMutation.isPending ? 'Saving…' : 'Save VNC Password'}
          </button>
        </form>
      </div>

      {deletingSecretKey && (
        <ConfirmDialog
          title="Delete this secret?"
          message="This secret will be permanently removed from the node. This cannot be undone."
          confirmLabel="Delete"
          destructive
          onConfirm={() => { deleteSecretMutation.mutate(deletingSecretKey); setDeletingSecretKey(null) }}
          onCancel={() => setDeletingSecretKey(null)}
        />
      )}
    </div>
  )
})
