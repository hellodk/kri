import { useState } from 'react'

export interface ToolStepData {
  n: number
  name: string
  args: Record<string, unknown>
  // Result fields (populated once tool_result arrives)
  ok?: boolean
  status?: string
  result?: unknown
  error?: string | null
  cached?: boolean
  pending?: boolean
}

function StatusDot({ step }: { step: ToolStepData }) {
  if (step.pending) {
    return <span className="w-2 h-2 rounded-full bg-amber-400 animate-pulse shrink-0" title="running" />
  }
  if (step.ok) {
    return <span className="w-2 h-2 rounded-full bg-green-500 shrink-0" title={step.status || 'ok'} />
  }
  return <span className="w-2 h-2 rounded-full bg-red-500 shrink-0" title={step.status || 'error'} />
}

/** One tool dispatch: the call (name + args) and, once it returns, its result. */
export function ToolResultCard({ step }: { step: ToolStepData }) {
  const [expanded, setExpanded] = useState(false)
  const argStr = Object.keys(step.args || {}).length ? JSON.stringify(step.args) : '{}'
  const hasResult = !step.pending
  const resultStr =
    step.result === undefined || step.result === null ? '' : JSON.stringify(step.result, null, 2)

  return (
    <div className="border border-gray-200 rounded-lg bg-white/70 text-xs overflow-hidden">
      <button
        onClick={() => hasResult && setExpanded((v) => !v)}
        className="w-full flex items-center gap-2 px-2.5 py-1.5 text-left hover:bg-gray-50 transition-colors"
        title={hasResult ? 'Toggle result' : 'Running…'}
      >
        <StatusDot step={step} />
        <span className="font-mono font-semibold text-gray-700">{step.name}</span>
        <span className="font-mono text-gray-400 truncate flex-1">{argStr}</span>
        {step.cached && <span className="text-[10px] text-blue-500 shrink-0">cached</span>}
        {hasResult && (
          <svg
            className={`w-3 h-3 text-gray-400 shrink-0 transition-transform ${expanded ? 'rotate-90' : ''}`}
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
            strokeWidth={2}
          >
            <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
          </svg>
        )}
      </button>
      {expanded && (
        <div className="border-t border-gray-100 px-2.5 py-1.5 bg-gray-50">
          {step.error ? (
            <pre className="whitespace-pre-wrap text-red-600 font-mono">{step.error}</pre>
          ) : (
            <pre className="whitespace-pre-wrap text-gray-700 font-mono max-h-48 overflow-y-auto">
              {resultStr || '(no output)'}
            </pre>
          )}
        </div>
      )}
    </div>
  )
}

/** A single agent reasoning step header ("Step N"). */
export function ToolStep({ iteration }: { iteration: number }) {
  return (
    <div className="flex items-center gap-2 text-[11px] uppercase tracking-wide text-gray-400 mt-2">
      <span className="h-px flex-1 bg-gray-200" />
      <span>Step {iteration}</span>
      <span className="h-px flex-1 bg-gray-200" />
    </div>
  )
}
