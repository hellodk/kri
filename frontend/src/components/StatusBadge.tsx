interface BadgeStyle { bg: string; text: string; dot: string }

const config: Record<string, BadgeStyle> = {
  online:  { bg: 'bg-emerald-100 border-emerald-300', text: 'text-emerald-800', dot: 'bg-emerald-500 animate-pulse' },
  offline: { bg: 'bg-red-100 border-red-300',         text: 'text-red-800',     dot: 'bg-red-500' },
  stale:   { bg: 'bg-amber-100 border-amber-300',     text: 'text-amber-800',   dot: 'bg-amber-500' },
  unknown: { bg: 'bg-gray-100 border-gray-300',       text: 'text-gray-700',    dot: 'bg-gray-400' },
}

export function StatusBadge({ status }: { status: string }) {
  const { bg, text, dot } = config[status] ?? config.unknown
  return (
    <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium border ${bg} ${text}`}>
      <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${dot}`} />
      {status}
    </span>
  )
}
