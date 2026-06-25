import { memo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { fleetApi } from '../../api/fleet'

// ResolvedCredentialPanel — shows which SSH credential a node resolves to,
// plus conflict/no-secret warnings (#702). Extracted from NodeDetail.tsx
// during the god-component decomposition (#787).
export const ResolvedCredentialPanel = memo(function ResolvedCredentialPanel({ nodeId }: { nodeId: string }) {
  const { data, isLoading } = useQuery({
    queryKey: ['node-credential', nodeId],
    queryFn: () => fleetApi.resolvedCredential(nodeId),
    staleTime: 60_000,
  })

  if (isLoading) {
    return (
      <div className="bg-white rounded-lg border border-gray-200 p-4 md:col-span-2">
        <h3 className="font-semibold text-gray-700 mb-3">SSH Credential</h3>
        <div className="space-y-2">
          <div className="h-4 w-48 bg-gray-200 rounded animate-pulse" />
          <div className="h-4 w-32 bg-gray-200 rounded animate-pulse" />
        </div>
      </div>
    )
  }

  if (!data) return null

  // Build display label for the source, embedding group priority when relevant.
  let sourceLabel = data.credential_source
  if (data.credential_source.startsWith('group:')) {
    const groupName = data.credential_source.slice('group:'.length)
    const grp = data.credential_bearing_groups.find((g) => g.name === groupName)
    if (grp) sourceLabel = `${data.credential_source} (priority ${grp.credential_priority})`
  }

  // Sort groups: highest priority first, alphabetical on ties — winner is index 0.
  const sortedGroups = [...data.credential_bearing_groups].sort((a, b) => {
    if (b.credential_priority !== a.credential_priority) return b.credential_priority - a.credential_priority
    return a.name.localeCompare(b.name)
  })
  const winner = sortedGroups[0]

  return (
    <div className="bg-white rounded-lg border border-gray-200 p-4 md:col-span-2">
      <h3 className="font-semibold text-gray-700 mb-3">SSH Credential</h3>

      {!data.has_usable_secret && (
        <div className="mb-3 flex items-center gap-2 px-3 py-2 bg-red-50 border border-red-200 rounded-lg text-sm text-red-700 font-medium">
          <span className="shrink-0">⚠</span>
          <span>No usable credential resolved — WebSSH/bootstrap will fail.</span>
        </div>
      )}

      {data.multi_group_conflict && (
        <div className="mb-3 px-3 py-2.5 bg-amber-50 border border-amber-200 rounded-lg">
          <div className="flex items-center gap-1.5 text-sm text-amber-800 font-medium mb-1.5">
            <span>⚡</span>
            Multi-group credential conflict
          </div>
          <p className="text-xs text-amber-700 mb-2">
            Multiple groups assign a credential to this node. Highest priority wins; ties broken alphabetically.
          </p>
          <div className="space-y-1">
            {sortedGroups.map((g) => (
              <div key={g.name} className="flex items-center gap-2 text-xs">
                <span
                  className={`font-mono ${
                    g.name === winner?.name ? 'text-amber-900 font-semibold' : 'text-amber-600'
                  }`}
                >
                  {g.name}
                </span>
                <span className="text-amber-500">priority {g.credential_priority}</span>
                {g.name === winner?.name && (
                  <span className="px-1.5 py-0.5 bg-amber-200 text-amber-900 rounded text-xs font-medium">
                    wins
                  </span>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      <dl className="grid grid-cols-3 gap-3 text-sm">
        <div>
          <dt className="text-xs text-gray-500 mb-0.5">Source</dt>
          <dd className="font-mono text-gray-800 text-xs break-all">{sourceLabel}</dd>
        </div>
        <div>
          <dt className="text-xs text-gray-500 mb-0.5">SSH User</dt>
          <dd className="font-mono text-gray-800 text-xs">{data.ssh_user}</dd>
        </div>
        <div>
          <dt className="text-xs text-gray-500 mb-0.5">Auth Mode</dt>
          <dd className="font-mono text-gray-800 text-xs">{data.auth_mode}</dd>
        </div>
      </dl>
    </div>
  )
})
