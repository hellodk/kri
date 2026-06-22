import { useState } from 'react'
import { DiffEditor } from '@monaco-editor/react'
import { artifactApi, type ArtifactSummary, type ArtifactDiff } from '../api/agent'

/**
 * Review surface for one quarantined artifact (#713): shows the generated
 * content vs the live tree as a Monaco side-by-side diff, with the validation
 * kind and add/remove counts. Promotion is intentionally absent — that is the
 * admin-only Phase-E action.
 */
export function ArtifactCard({ artifact }: { artifact: ArtifactSummary }) {
  const [target, setTarget] = useState('')
  const [diff, setDiff] = useState<ArtifactDiff | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const kind = (artifact.metadata?.kind as string) || 'artifact'
  const lang = kind === 'salt_state' ? 'yaml' : 'yaml'

  const loadDiff = async () => {
    setLoading(true)
    setError(null)
    try {
      setDiff(await artifactApi.diff(artifact.session_id, artifact.filename, target || undefined))
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="border border-gray-200 rounded-lg bg-white/80 text-xs overflow-hidden">
      <div className="flex items-center gap-2 px-3 py-2 bg-gray-50 border-b border-gray-100">
        <span className="font-mono font-semibold text-gray-700">{artifact.filename}</span>
        <span className="px-1.5 py-0.5 rounded bg-blue-100 text-blue-700 text-[10px]">{kind}</span>
        <span className="text-gray-400">{artifact.size} B</span>
        <span className="text-gray-300 font-mono truncate flex-1 text-right">{artifact.session_id.slice(0, 8)}</span>
      </div>
      <div className="p-3 space-y-2">
        <div className="flex gap-2">
          <input
            value={target}
            onChange={(e) => setTarget(e.target.value)}
            placeholder="live target path (e.g. deploy_config.yml) — blank = treat as new"
            className="flex-1 border border-gray-300 rounded px-2 py-1 text-xs focus:outline-none focus:ring-1 focus:ring-blue-500"
          />
          <button
            onClick={loadDiff}
            disabled={loading}
            className="px-2.5 py-1 bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white rounded text-xs"
          >
            {loading ? 'Diffing…' : 'Diff vs live'}
          </button>
        </div>
        {error && <p className="text-red-600">⚠ {error}</p>}
        {diff && (
          <>
            <div className="flex items-center gap-3 text-[11px]">
              <span className="text-green-600">+{diff.added}</span>
              <span className="text-red-600">−{diff.removed}</span>
              {diff.is_new && <span className="px-1.5 py-0.5 rounded bg-amber-100 text-amber-700">new file</span>}
            </div>
            <div className="border border-gray-200 rounded overflow-hidden" style={{ height: 320 }}>
              <DiffEditor
                original={diff.original}
                modified={diff.modified}
                language={lang}
                theme="vs"
                options={{
                  readOnly: true,
                  renderSideBySide: true,
                  minimap: { enabled: false },
                  scrollBeyondLastLine: false,
                  fontSize: 12,
                }}
              />
            </div>
          </>
        )}
      </div>
    </div>
  )
}
