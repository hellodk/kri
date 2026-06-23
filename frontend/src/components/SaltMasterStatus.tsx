import { useQuery } from '@tanstack/react-query'
import { saltMastersApi, type SaltMaster } from '../api/saltMasters'
import { saltMasterBadge } from '../lib/saltMasterHelpers'

/**
 * Pick the master whose health best represents the fleet's control plane:
 * the default master if one is flagged, otherwise the first enabled master,
 * otherwise the first configured master. Returns null when none exist.
 */
function pickMaster(masters: SaltMaster[]): SaltMaster | null {
  if (masters.length === 0) return null
  const enabled = masters.filter((m) => m.enabled)
  const pool = enabled.length > 0 ? enabled : masters
  return pool.find((m) => m.is_default) ?? pool[0]
}

const DOT: Record<string, string> = {
  healthy: 'bg-green-500',
  degraded: 'bg-amber-500',
  unreachable: 'bg-red-500',
  unknown: 'bg-gray-300',
}

export function SaltMasterStatus() {
  // Source of truth is the configured SaltMaster row — its api_url is derived
  // server-side from address + salt_api_port + use_tls, and its `status` is the
  // backend-computed health (the worker probes that derived URL). No port or
  // scheme is hardcoded here.
  const { data: masters, isLoading } = useQuery({
    queryKey: ['salt-masters'],
    queryFn: saltMastersApi.list,
    staleTime: 30_000,
    refetchInterval: 60_000,
  })

  const master = masters ? pickMaster(masters) : null

  if (!master) {
    return (
      <div className="flex items-center gap-2 px-3 py-2 rounded-lg bg-gray-50 border border-gray-200 text-sm">
        <span className="w-2 h-2 rounded-full bg-gray-300 flex-shrink-0" />
        <span className="text-gray-500">
          {isLoading ? 'Checking salt master…' : 'Salt master not configured'}
        </span>
      </div>
    )
  }

  const badge = saltMasterBadge(master.status)
  const dot = DOT[master.status] ?? DOT.unknown
  const target = master.api_url ?? master.address

  return (
    <div
      className={`flex items-center gap-2 px-3 py-2 rounded-lg border border-gray-200 text-sm ${badge.bgClass}`}
      title={master.last_error ?? undefined}
    >
      <span className={`w-2 h-2 rounded-full flex-shrink-0 ${dot}`} />
      <div className="min-w-0">
        <span className={`font-medium ${badge.textClass}`}>Salt master</span>
        <span className="text-gray-500 ml-1.5 font-mono text-xs truncate">{target}</span>
      </div>
      <span className={`text-xs ml-auto flex-shrink-0 ${badge.textClass}`}>{badge.label}</span>
    </div>
  )
}
