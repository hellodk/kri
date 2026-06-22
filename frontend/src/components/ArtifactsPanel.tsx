import { useEffect, useState, useCallback } from 'react'
import { artifactApi, type ArtifactSummary } from '../api/agent'
import { ArtifactCard } from './ArtifactCard'

/**
 * Lists the operator's quarantined artifacts (#713). Each row expands into an
 * ArtifactCard for diff review. Read-only review surface — no promote here.
 */
export function ArtifactsPanel() {
  const [artifacts, setArtifacts] = useState<ArtifactSummary[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [expanded, setExpanded] = useState<string | null>(null)

  const refresh = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await artifactApi.list()
      setArtifacts(res.artifacts)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    // Mount-time load of the artifact list; the loading flag is intentional.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void refresh()
  }, [refresh])

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <span className="text-xs text-gray-500">Quarantined artifacts ({artifacts.length})</span>
        <button onClick={() => void refresh()} className="text-xs text-blue-600 hover:text-blue-700">
          Refresh
        </button>
      </div>
      {loading && <p className="text-xs text-gray-400">Loading…</p>}
      {error && <p className="text-xs text-red-600">⚠ {error}</p>}
      {!loading && artifacts.length === 0 && (
        <p className="text-xs text-gray-400 text-center py-4">
          No artifacts yet. Ask the agent to generate a playbook or state — it lands here for review, never live.
        </p>
      )}
      {artifacts.map((a) => (
        <div key={a.id} className="border border-gray-200 rounded-lg overflow-hidden">
          <button
            onClick={() => setExpanded(expanded === a.id ? null : a.id)}
            className="w-full flex items-center gap-2 px-3 py-2 text-left text-xs hover:bg-gray-50"
          >
            <span className="font-mono font-semibold text-gray-700">{a.filename}</span>
            <span className="text-gray-400 flex-1">{(a.metadata?.kind as string) || ''}</span>
            <span className="text-gray-400">{a.size} B</span>
          </button>
          {expanded === a.id && (
            <div className="p-2 bg-gray-50">
              <ArtifactCard artifact={a} />
            </div>
          )}
        </div>
      ))}
    </div>
  )
}
