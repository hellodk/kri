import { useMutation, useQueryClient } from '@tanstack/react-query'
import { formatDistanceToNow } from 'date-fns'
import { fleetApi } from '../api/fleet'
import { useToastStore } from '../stores/toastStore'
import type { SshState } from '../types'

interface SshStyle {
  dot: string
  text: string
  label: string
}

// Idea 2 "compact dual-dot": one labeled SSH dot. Four states, because the probe
// distinguishes "port open but auth rejected" (fix creds) from "host down".
const SSH_STYLES: Record<SshState, SshStyle> = {
  ok:          { dot: 'bg-emerald-500', text: 'text-gray-600', label: 'reachable' },
  auth_failed: { dot: 'bg-amber-500',   text: 'text-amber-700', label: 'auth failed' },
  unreachable: { dot: 'bg-red-500',     text: 'text-red-700',   label: 'unreachable' },
  unknown:     { dot: 'bg-gray-300',    text: 'text-gray-400',  label: 'not checked' },
}

function relTime(iso: string | null | undefined): string {
  if (!iso) return 'never'
  try {
    return formatDistanceToNow(new Date(iso), { addSuffix: false })
  } catch {
    return ''
  }
}

/**
 * SSH reachability row for the Fleet table's Connectivity cell (#356-ui).
 * Shows the cached probe state as a labeled dot plus an on-demand refresh that
 * runs a live probe for this one node.
 */
export function SshIndicator({
  nodeId,
  state,
  checkedAt,
  detail,
  canManage = false,
}: {
  nodeId: string
  state: SshState | null | undefined
  checkedAt: string | null | undefined
  detail: string | null | undefined
  canManage?: boolean
}) {
  const qc = useQueryClient()
  const toast = useToastStore((s) => s.add)
  const style = SSH_STYLES[state ?? 'unknown']

  const test = useMutation({
    mutationFn: () => fleetApi.sshTest(nodeId),
    onSuccess: (res) => {
      qc.invalidateQueries({ queryKey: ['nodes'] })
      qc.invalidateQueries({ queryKey: ['node', nodeId] })
      const s = SSH_STYLES[res.ssh_state]
      toast(`SSH: ${s.label}`, res.ssh_state === 'ok' ? 'success' : res.ssh_state === 'unknown' ? 'info' : 'warning')
    },
    onError: () => toast('SSH probe failed', 'error'),
  })

  const checkedLabel = checkedAt ? `· ${relTime(checkedAt)}` : ''
  const title = detail ?? (checkedAt ? `Last checked ${relTime(checkedAt)} ago` : 'Never probed')

  return (
    <div className="flex items-center gap-1.5 text-xs" title={title}>
      <span className="text-[10px] font-semibold uppercase tracking-wide text-gray-400 w-7 shrink-0">SSH</span>
      <span className={`w-2 h-2 rounded-full shrink-0 ${test.isPending ? 'bg-brand-400 animate-pulse' : style.dot}`} />
      <span className={style.text}>
        {test.isPending ? 'testing…' : style.label}
        {!test.isPending && <span className="text-gray-300"> {checkedLabel}</span>}
      </span>
      {canManage && (
        <button
          type="button"
          onClick={() => test.mutate()}
          disabled={test.isPending}
          title="Test SSH now"
          aria-label="Test SSH connectivity now"
          className="ml-0.5 text-gray-300 hover:text-brand-600 disabled:opacity-40 disabled:cursor-not-allowed"
        >
          <svg
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            className={`w-3.5 h-3.5 ${test.isPending ? 'animate-spin' : ''}`}
          >
            <path d="M21 12a9 9 0 1 1-2.64-6.36" />
            <path d="M21 4v5h-5" />
          </svg>
        </button>
      )}
    </div>
  )
}
