import { memo } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { formatDistanceToNow } from 'date-fns'
import { fleetApi } from '../../api/fleet'
import { StatusBadge } from '../../components/StatusBadge'
import { useToastStore } from '../../stores/toastStore'
import type { NodeDetail as NodeDetailData } from '../../types'

// ConnectivityPanel — shows the two independent reachability axes side by side:
// Salt minion presence (node.status) and SSH reachability (node.ssh_state), with
// an on-demand "Test SSH now" probe and an actionable message on auth failure.
// Extracted from NodeDetail.tsx during the god-component decomposition (#787).

const SSH_PILL: Record<string, { cls: string; label: string }> = {
  ok:          { cls: 'bg-emerald-100 text-emerald-800 border-emerald-300', label: 'reachable' },
  auth_failed: { cls: 'bg-amber-100 text-amber-800 border-amber-300',       label: 'auth failed' },
  unreachable: { cls: 'bg-red-100 text-red-800 border-red-300',             label: 'unreachable' },
  unknown:     { cls: 'bg-gray-100 text-gray-600 border-gray-300',          label: 'not checked' },
}

export const ConnectivityPanel = memo(function ConnectivityPanel({
  node,
  canManage,
}: {
  node: NodeDetailData
  canManage: boolean
}) {
  const qc = useQueryClient()
  const toast = useToastStore((s) => s.add)
  const sshState = node.ssh_state ?? 'unknown'
  const pill = SSH_PILL[sshState] ?? SSH_PILL.unknown

  const test = useMutation({
    mutationFn: () => fleetApi.sshTest(node.id),
    onSuccess: (res) => {
      qc.invalidateQueries({ queryKey: ['node', node.id] })
      qc.invalidateQueries({ queryKey: ['nodes'] })
      const p = SSH_PILL[res.ssh_state] ?? SSH_PILL.unknown
      toast(`SSH: ${p.label}`, res.ssh_state === 'ok' ? 'success' : res.ssh_state === 'unknown' ? 'info' : 'warning')
    },
    onError: () => toast('SSH probe failed', 'error'),
  })

  const checked = node.ssh_checked_at
    ? `${formatDistanceToNow(new Date(node.ssh_checked_at), { addSuffix: true })}`
    : 'never'

  return (
    <div className="bg-white rounded-lg border border-gray-200 p-4 md:col-span-2">
      <h3 className="font-semibold text-gray-700 mb-3">Connectivity</h3>
      <dl className="grid grid-cols-2 gap-3 text-sm">
        <div>
          <dt className="text-xs text-gray-500 mb-1">Salt minion</dt>
          <dd className="flex items-center gap-2">
            <StatusBadge status={node.status} />
            <span className="text-xs text-gray-400">
              {node.last_seen_at ? formatDistanceToNow(new Date(node.last_seen_at), { addSuffix: true }) : 'never seen'}
            </span>
          </dd>
        </div>
        <div>
          <dt className="text-xs text-gray-500 mb-1">SSH reachability</dt>
          <dd className="flex items-center gap-2 flex-wrap">
            <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium border ${pill.cls}`}>
              {test.isPending ? 'testing…' : pill.label}
            </span>
            <span className="text-xs text-gray-400">checked {checked}</span>
            {canManage && (
              <button
                onClick={() => test.mutate()}
                disabled={test.isPending}
                className="text-xs px-2 py-1 rounded-md bg-brand-50 text-brand-700 border border-brand-200 hover:bg-brand-100 disabled:opacity-50"
              >
                {test.isPending ? 'Testing…' : 'Test SSH now'}
              </button>
            )}
          </dd>
        </div>
      </dl>
      {sshState === 'auth_failed' && (
        <div className="mt-3 px-3 py-2 bg-amber-50 border border-amber-200 rounded-lg text-xs text-amber-800">
          Port 22 is open but authentication was rejected. Check the resolved SSH credential below — the password/key may
          be wrong, or the controller&apos;s public key may not be authorized on the host.
        </div>
      )}
      {sshState === 'unreachable' && (
        <div className="mt-3 px-3 py-2 bg-red-50 border border-red-200 rounded-lg text-xs text-red-700">
          TCP port 22 is closed or timed out — the host may be down, firewalled, or the IP on record may be wrong.
        </div>
      )}
      {node.ssh_detail && (
        <p className="mt-2 text-[11px] text-gray-600 font-mono break-all">{node.ssh_detail}</p>
      )}
    </div>
  )
})
