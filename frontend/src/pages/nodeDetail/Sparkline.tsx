// Tiny inline SVG sparkline used on NodeDetail resource cards. Extracted from
// NodeDetail.tsx so any future tab can render a sparkline without depending on
// the page module (#arch-nodedetail).

interface SparklineProps {
  data: Array<{ t: number; v: number }>
  color?: string
  height?: number
}

export function Sparkline({ data, color = '#3b82f6', height = 40 }: SparklineProps) {
  if (!data || data.length < 2) return <span className="text-xs text-gray-400">No data</span>
  const vals = data.map((d) => d.v)
  const min = Math.min(...vals)
  const max = Math.max(...vals)
  const range = max - min || 1
  const w = 180
  const pts = data.map((d, i) => {
    const x = (i / (data.length - 1)) * w
    const y = height - ((d.v - min) / range) * (height - 4) - 2
    return `${x},${y}`
  })
  const last = vals[vals.length - 1]
  return (
    <div className="flex items-center gap-2">
      <svg width={w} height={height} className="shrink-0">
        <polyline points={pts.join(' ')} fill="none" stroke={color} strokeWidth="1.5" />
      </svg>
      <span className="text-sm font-mono font-semibold text-gray-800">{last.toFixed(1)}</span>
    </div>
  )
}
