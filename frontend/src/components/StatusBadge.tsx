interface BadgeStyle { bg: string; text: string; dot: string }

const config: Record<string, BadgeStyle> = {
  online:  { bg: 'bg-emerald-950/80 border-emerald-800/60', text: 'text-emerald-400', dot: 'bg-emerald-400 animate-pulse' },
  offline: { bg: 'bg-red-950/80 border-red-800/60',         text: 'text-red-400',     dot: 'bg-red-400' },
  stale:   { bg: 'bg-amber-950/80 border-amber-800/60',     text: 'text-amber-400',   dot: 'bg-amber-500' },
  unknown: { bg: 'bg-gray-800/80 border-gray-700/60',       text: 'text-gray-400',    dot: 'bg-gray-500' },
}

export function StatusBadge({ status }: { status: string }) {
  const { bg, text, dot } = config[status] ?? config.unknown
  return (
    <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium border ${bg} ${text}`}>
      <span className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${dot}`} />
      {status}
    </span>
  )
}
