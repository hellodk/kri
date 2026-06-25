import { useRef, useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { formatDistanceToNow } from 'date-fns'
import { fleetApi } from '../api/fleet'
import { useToastStore } from '../stores/toastStore'
import type { HealthState, MasterStatus, SshState } from '../types'

interface HealthStyle {
  badge: string
  dot: string
  label: string
}

// Worst-of rollup of Salt presence + SSH state. The server derives `health`;
// deriveHealth() mirrors that logic as a fallback so the badge still renders if
// the field is ever missing from a payload.
const HEALTH_STYLES: Record<HealthState, HealthStyle> = {
  online:      { badge: 'bg-emerald-100 border-emerald-300 text-emerald-800', dot: 'bg-emerald-500 animate-pulse', label: 'Online' },
  degraded:    { badge: 'bg-amber-100 border-amber-300 text-amber-800',       dot: 'bg-amber-500',                label: 'Degraded' },
  down:        { badge: 'bg-red-100 border-red-300 text-red-800',             dot: 'bg-red-500',                  label: 'Down' },
  unknown:     { badge: 'bg-gray-100 border-gray-300 text-gray-700',          dot: 'bg-gray-400',                 label: 'Unknown' },
  maintenance: { badge: 'bg-indigo-100 border-indigo-300 text-indigo-800',    dot: 'bg-indigo-500',               label: 'Maintenance' },
}

const PRESENCE_DOT: Record<string, string> = {
  online: 'bg-emerald-500', stale: 'bg-amber-500', offline: 'bg-red-500', unknown: 'bg-gray-400',
}

const SSH_META: Record<SshState, { dot: string; label: string }> = {
  ok:          { dot: 'bg-emerald-500', label: 'reachable' },
  auth_failed: { dot: 'bg-amber-500',   label: 'auth failed' },
  unreachable: { dot: 'bg-red-500',     label: 'unreachable' },
  unknown:     { dot: 'bg-gray-300',    label: 'not checked' },
}

const MASTER_META: Record<MasterStatus, { dot: string; label: string }> = {
  healthy:     { dot: 'bg-emerald-500', label: 'healthy' },
  degraded:    { dot: 'bg-amber-500',   label: 'degraded' },
  unreachable: { dot: 'bg-red-500',     label: 'unreachable' },
  unknown:     { dot: 'bg-gray-300',    label: 'not checked' },
}

function deriveHealth(
  status: string,
  sshState: SshState | null | undefined,
  maintenanceMode: boolean,
  masterStatus: MasterStatus | null | undefined,
): HealthState {
  if (maintenanceMode) return 'maintenance'
  const minion = ({ online: 'good', stale: 'warn', offline: 'bad' } as const)[status as 'online' | 'stale' | 'offline']
  const ssh = sshState ? ({ ok: 'good', auth_failed: 'warn', unreachable: 'bad' } as const)[sshState as 'ok' | 'auth_failed' | 'unreachable'] : undefined
  const levels: Array<'good' | 'warn' | 'bad' | undefined> = [minion, ssh]
  if (masterStatus != null) {
    levels.push(({ healthy: 'good', degraded: 'warn', unreachable: 'bad' } as const)[masterStatus as 'healthy' | 'degraded' | 'unreachable'])
  }
  if (levels.includes('bad')) return 'down'
  if (levels.includes('warn')) return 'degraded'
  if (minion === 'good') return 'online'
  if (levels.includes('good')) return 'degraded'
  return 'unknown'
}

function relTime(iso: string | null | undefined): string | null {
  if (!iso) return null
  try {
    return formatDistanceToNow(new Date(iso), { addSuffix: true })
  } catch {
    return null
  }
}

function RefreshIcon({ spinning = false }: { spinning?: boolean }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={`w-3.5 h-3.5 flex-shrink-0 ${spinning ? 'animate-spin' : ''}`}
      aria-hidden="true"
    >
      <path d="M21 12a9 9 0 1 1-2.64-6.36" />
      <path d="M21 3v6h-6" />
    </svg>
  )
}

/**
 * Unified node-health indicator (#356 follow-up). One badge replaces the stacked
 * Salt-status + SSH-reachability rows in the Fleet table: it shows the worst-of
 * rollup at a glance and reveals the full per-dimension breakdown on hover, with
 * an on-demand "Re-check all" refresh in the tooltip that re-probes SSH and
 * re-pulls the minion + master dimensions in one click.
 */
export function HealthBadge({
  nodeId,
  health,
  status,
  sshState,
  sshCheckedAt,
  sshDetail,
  lastSeenAt,
  maintenanceMode = false,
  isMaster = false,
  masterStatus,
  canManage = false,
}: {
  nodeId: string
  health?: HealthState
  status: string
  sshState?: SshState | null
  sshCheckedAt?: string | null
  sshDetail?: string | null
  lastSeenAt?: string | null
  maintenanceMode?: boolean
  isMaster?: boolean
  masterStatus?: MasterStatus | null
  canManage?: boolean
}) {
  const qc = useQueryClient()
  const toast = useToastStore((s) => s.add)
  const [open, setOpen] = useState(false)
  const closeTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  const effectiveMasterStatus = isMaster ? (masterStatus ?? 'unknown') : null
  const resolved: HealthState = health ?? deriveHealth(status, sshState, maintenanceMode, effectiveMasterStatus)
  const style = HEALTH_STYLES[resolved] ?? HEALTH_STYLES.unknown
  const ssh = SSH_META[sshState ?? 'unknown']
  const master = effectiveMasterStatus ? MASTER_META[effectiveMasterStatus] : null

  // Re-check every dimension shown in the tooltip. SSH is the one actively
  // probed here (synchronous); minion presence and master control-plane status
  // are server-derived columns on the node payload, so invalidating the node /
  // fleet / health queries re-pulls their freshest values in the same click.
  const test = useMutation({
    mutationFn: () => fleetApi.sshTest(nodeId),
    onSuccess: (res) => {
      qc.invalidateQueries({ queryKey: ['nodes'] })
      qc.invalidateQueries({ queryKey: ['node', nodeId] })
      qc.invalidateQueries({ queryKey: ['fleet-health'] })
      qc.invalidateQueries({ queryKey: ['node-health', nodeId] })
      qc.invalidateQueries({ queryKey: ['salt-masters'] })
      const s = SSH_META[res.ssh_state]
      toast(`Re-checked · SSH: ${s.label}`, res.ssh_state === 'ok' ? 'success' : res.ssh_state === 'unknown' ? 'info' : 'warning')
    },
    onError: () => toast('Re-check failed', 'error'),
  })

  const show = () => {
    if (closeTimer.current) clearTimeout(closeTimer.current)
    setOpen(true)
  }
  const hide = () => {
    closeTimer.current = setTimeout(() => setOpen(false), 120)
  }

  const seen = relTime(lastSeenAt)
  const checked = relTime(sshCheckedAt)

  return (
    <div className="relative inline-block" onMouseEnter={show} onMouseLeave={hide}>
      <span
        className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium border cursor-default ${style.badge}`}
        tabIndex={0}
        onFocus={show}
        onBlur={hide}
        aria-label={`Health: ${style.label}`}
      >
        <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${test.isPending ? 'bg-brand-400 animate-pulse' : style.dot}`} />
        {style.label}
      </span>

      {open && (
        <div
          role="tooltip"
          className="absolute z-20 left-0 top-full mt-1.5 w-72 rounded-lg bg-white text-gray-700 text-xs p-3 shadow-xl ring-1 ring-gray-200 border border-gray-100"
          onMouseEnter={show}
          onMouseLeave={hide}
        >
          <div className="flex items-center gap-2 font-semibold text-gray-900 mb-2 pb-2 border-b border-gray-100">
            <span className={`w-2 h-2 rounded-full ${style.dot}`} />
            {style.label}
          </div>

          <div className="font-mono leading-relaxed text-gray-600 space-y-0.5">
            <div className="flex items-center gap-2">
              <span className={`w-1.5 h-1.5 rounded-full ${PRESENCE_DOT[status] ?? 'bg-gray-400'}`} />
              Minion: {status} · {seen ?? 'never seen'}
            </div>
            <div className="flex items-center gap-2">
              <span className={`w-1.5 h-1.5 rounded-full ${ssh.dot}`} />
              SSH: {test.isPending ? 'testing…' : ssh.label} · {checked ?? 'never probed'}
            </div>
            {master && (
              <div className="flex items-center gap-2">
                <span className={`w-1.5 h-1.5 rounded-full ${master.dot}`} />
                Master: {master.label}
              </div>
            )}
          </div>

          {resolved === 'degraded' && status !== 'online' && (ssh.label === 'reachable') && (
            <div className="mt-2 text-amber-800 bg-amber-50 border border-amber-100 rounded px-2 py-1">
              Reachable over SSH but the Salt minion isn&apos;t reporting — check the minion.
            </div>
          )}

          {maintenanceMode && (
            <div className="mt-2 text-indigo-700 bg-indigo-50 border border-indigo-100 rounded px-2 py-1">
              In maintenance mode — alerts suppressed.
            </div>
          )}

          {sshDetail && (
            <div className="mt-2 pt-2 border-t border-gray-100 text-gray-500 break-words">{sshDetail}</div>
          )}

          {canManage && (
            <button
              type="button"
              onClick={() => test.mutate()}
              disabled={test.isPending}
              title="Re-check all health checks (minion, SSH, master)"
              aria-label="Re-check all health checks"
              className="mt-2.5 w-full inline-flex items-center justify-center gap-1.5 text-xs px-2 py-1 rounded-md bg-brand-50 text-brand-700 border border-brand-200 hover:bg-brand-100 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              <RefreshIcon spinning={test.isPending} />
              {test.isPending ? 'Re-checking…' : 'Re-check all'}
            </button>
          )}
        </div>
      )}
    </div>
  )
}
