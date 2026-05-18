interface SeverityStyle { bg: string; text: string; dot: string }

function severityStyle(score: number): SeverityStyle {
  if (score <= 5)  return { bg: 'bg-emerald-100 border-emerald-300', text: 'text-emerald-800', dot: 'bg-emerald-500' }
  if (score <= 20) return { bg: 'bg-blue-100 border-blue-300',       text: 'text-blue-800',    dot: 'bg-blue-500' }
  if (score <= 50) return { bg: 'bg-amber-100 border-amber-300',     text: 'text-amber-800',   dot: 'bg-amber-500' }
  if (score <= 80) return { bg: 'bg-orange-100 border-orange-300',   text: 'text-orange-800',  dot: 'bg-orange-500' }
  return { bg: 'bg-red-100 border-red-300', text: 'text-red-800', dot: 'bg-red-500 animate-pulse' }
}

export function DriftBadge({ score }: { score: number }) {
  const { bg, text, dot } = severityStyle(score)
  return (
    <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold border tabular-nums ${bg} ${text}`}>
      <span className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${dot}`} />
      {score}
    </span>
  )
}
