interface SeverityStyle { bg: string; text: string; dot: string }

function severityStyle(score: number): SeverityStyle {
  if (score <= 5)  return { bg: 'bg-emerald-950/80 border-emerald-800/60', text: 'text-emerald-400', dot: 'bg-emerald-400' }
  if (score <= 20) return { bg: 'bg-blue-950/80 border-blue-800/60',       text: 'text-blue-400',    dot: 'bg-blue-400' }
  if (score <= 50) return { bg: 'bg-amber-950/80 border-amber-800/60',     text: 'text-amber-400',   dot: 'bg-amber-400' }
  if (score <= 80) return { bg: 'bg-orange-950/80 border-orange-800/60',   text: 'text-orange-400',  dot: 'bg-orange-400' }
  return { bg: 'bg-red-950/80 border-red-800/60', text: 'text-red-400', dot: 'bg-red-400 animate-pulse' }
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
